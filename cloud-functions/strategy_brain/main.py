import json
import logging
import os
import sys
import uuid
from datetime import date, datetime, timedelta

from google.cloud import bigquery

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from conf.conf import load_config

logging.basicConfig(level=logging.INFO)

FORMULA_VERSION = "brain-context-v1"
WEIGHT_FIELDS = (
    "fear_weight",
    "monetary_weight",
    "earnings_weight",
    "company_lifecycle_weight",
    "quality_weight",
    "valuation_state_weight",
    "political_risk_weight",
    "crypto_cycle_weight",
)


def _parse_date(value, field):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must use YYYY-MM-DD") from exc


def _table_ddl(config):
    return [
        f"""
        CREATE TABLE IF NOT EXISTS `{config['runs_table']}` (
          run_id STRING NOT NULL, created_at TIMESTAMP NOT NULL, status STRING NOT NULL,
          formula_version STRING NOT NULL, training_start DATE NOT NULL, training_end DATE NOT NULL,
          validation_start DATE NOT NULL, validation_end DATE NOT NULL, objective_definition STRING NOT NULL,
          data_quality_notes STRING, production_change_allowed BOOL NOT NULL
        ) CLUSTER BY status, formula_version
        """,
        f"""
        CREATE TABLE IF NOT EXISTS `{config['candidates_table']}` (
          run_id STRING NOT NULL, candidate_id STRING NOT NULL, candidate_status STRING NOT NULL,
          formula_version STRING NOT NULL, candidate_label STRING NOT NULL, candidate_reason STRING NOT NULL,
          training_start DATE NOT NULL, training_end DATE NOT NULL, validation_start DATE NOT NULL, validation_end DATE NOT NULL,
          fear_weight FLOAT64 NOT NULL, monetary_weight FLOAT64 NOT NULL, earnings_weight FLOAT64 NOT NULL,
          company_lifecycle_weight FLOAT64 NOT NULL, quality_weight FLOAT64 NOT NULL,
          valuation_state_weight FLOAT64 NOT NULL, political_risk_weight FLOAT64 NOT NULL,
          crypto_cycle_weight FLOAT64 NOT NULL, min_trade_score_add FLOAT64 NOT NULL,
          position_size_multiplier FLOAT64 NOT NULL, formula_expression STRING NOT NULL,
          created_at TIMESTAMP NOT NULL
        ) CLUSTER BY run_id, candidate_status
        """,
        f"""
        CREATE TABLE IF NOT EXISTS `{config['audits_table']}` (
          run_id STRING NOT NULL, created_at TIMESTAMP NOT NULL, audit_status STRING NOT NULL,
          selected_candidates_json STRING NOT NULL, evidence_json STRING NOT NULL,
          ai_interpretation STRING, model_name STRING, production_change_allowed BOOL NOT NULL
        ) CLUSTER BY run_id, audit_status
        """,
    ]


def _baseline(client, config):
    query = f"""
      SELECT * EXCEPT(variant_id, variant_name, variant_description)
      FROM `{config['variants_table']}`
      WHERE variant_id = 'baseline_actual'
      LIMIT 1
    """
    rows = list(client.query(query).result())
    if not rows:
        raise RuntimeError("baseline_actual was not found in trading_backtest_context_variants")
    return dict(rows[0].items())


def _formula_expression(weights):
    terms = " + ".join(f"{field}*{field.replace('_weight', '_component')}" for field in WEIGHT_FIELDS)
    return (
        "contextual_setup_score = setup_score + "
        f"{terms}; threshold = min_trade_score + {weights['min_trade_score_add']}; "
        f"position_notional = base_position_notional * {weights['position_size_multiplier']}; "
        "net_pnl = position_notional * (gross_return - estimated_roundtrip_cost_pct / 100)"
    )


def _candidate_rows(run_id, baseline, windows):
    candidates = [("baseline", "Control sin cambio", "Control para comparar cambios de pesos.", {})]
    for field in WEIGHT_FIELDS:
        candidates.append((f"{field}_down", f"Reducir {field}", "Prueba un ajuste conservador aislado.", {field: round(float(baseline[field]) - 0.25, 2)}))
        candidates.append((f"{field}_up", f"Aumentar {field}", "Prueba un ajuste aislado con mayor sensibilidad.", {field: round(float(baseline[field]) + 0.25, 2)}))
    candidates += [
        ("threshold_up", "Exigir setup mayor", "Reduce sobreoperacion elevando el filtro de entrada.", {"min_trade_score_add": 0.25, "position_size_multiplier": 0.85}),
        ("risk_down", "Reducir exposicion", "Mantiene señales pero reduce notional para medir riesgo neto.", {"position_size_multiplier": 0.70}),
        ("quality_risk", "Calidad defensiva", "Refuerza calidad y valoracion, penaliza contexto de riesgo.", {"quality_weight": 0.75, "valuation_state_weight": 0.60, "fear_weight": 0.60, "political_risk_weight": 0.50, "position_size_multiplier": 0.80}),
    ]
    records = []
    for suffix, label, reason, overrides in candidates:
        weights = {key: float(baseline[key]) for key in WEIGHT_FIELDS}
        weights["min_trade_score_add"] = float(baseline["min_trade_score_add"])
        weights["position_size_multiplier"] = float(baseline["position_size_multiplier"])
        weights.update(overrides)
        candidate_id = f"brain_{run_id.replace('-', '')[:12]}_{suffix}"
        records.append({
            "run_id": run_id,
            "candidate_id": candidate_id,
            "candidate_status": "BACKTEST_ONLY",
            "formula_version": FORMULA_VERSION,
            "candidate_label": label,
            "candidate_reason": reason,
            **{key: value.isoformat() for key, value in windows.items()},
            **weights,
            "formula_expression": _formula_expression(weights),
            "created_at": datetime.utcnow().isoformat(),
        })
    return records


def _generate(client, config, payload):
    training_start = _parse_date(payload.get("training_start", "2019-01-01"), "training_start")
    training_end = _parse_date(payload.get("training_end", "2024-12-31"), "training_end")
    validation_start = _parse_date(payload.get("validation_start", "2025-01-01"), "validation_start")
    validation_end = _parse_date(payload.get("validation_end", str(date.today() - timedelta(days=1))), "validation_end")
    if not training_start <= training_end < validation_start <= validation_end:
        raise ValueError("Require training_start <= training_end < validation_start <= validation_end")

    run_id = payload.get("run_id") or f"brain-{datetime.utcnow():%Y%m%d%H%M%S}-{uuid.uuid4().hex[:6]}"
    windows = {"training_start": training_start, "training_end": training_end, "validation_start": validation_start, "validation_end": validation_end}
    baseline = _baseline(client, config)
    candidates = _candidate_rows(run_id, baseline, windows)
    objective = "0.35 normalized net PnL + 0.25 capped profit factor + 0.20 win rate - 0.15 max drawdown - 0.05 tail loss; net of spread and slippage"
    client.insert_rows_json(config["runs_table"], [{
        "run_id": run_id, "created_at": datetime.utcnow().isoformat(), "status": "CANDIDATES_READY",
        "formula_version": FORMULA_VERSION, **{key: value.isoformat() for key, value in windows.items()}, "objective_definition": objective,
        "data_quality_notes": "Daily price history is broad; earnings/news/macro historical coverage must be audited before interpretation.",
        "production_change_allowed": False,
    }])
    errors = client.insert_rows_json(config["candidates_table"], candidates)
    if errors:
        raise RuntimeError(f"Could not save candidates: {errors}")
    return {"run_id": run_id, "candidate_count": len(candidates), "status": "CANDIDATES_READY", "next_step": "Run Dataform, then call phase=review with this run_id."}


def _review(client, config, payload):
    run_id = payload.get("run_id")
    if not run_id:
        latest = list(client.query(
            f"SELECT run_id FROM `{config['runs_table']}` WHERE status = 'CANDIDATES_READY' ORDER BY created_at DESC LIMIT 1"
        ).result())
        if not latest:
            raise ValueError("run_id is required when no candidate run exists")
        run_id = latest[0]["run_id"]
    query = f"""
      SELECT * FROM `{config['summary_table']}`
      WHERE run_id = @run_id AND evaluation_split = 'VALIDATION'
      ORDER BY strategy_version, mechanical_verdict DESC, net_pnl_clp DESC
    """
    rows = [dict(row.items()) for row in client.query(query, job_config=bigquery.QueryJobConfig(query_parameters=[bigquery.ScalarQueryParameter("run_id", "STRING", run_id)])).result()]
    if not rows:
        raise RuntimeError("No validation summary exists yet. Run Dataform after generating candidates.")
    eligible = [row for row in rows if row["mechanical_verdict"] == "ELIGIBLE_FOR_REVIEW"]
    prompt = (
        "Eres auditor de backtesting. Responde en espanol y solo interpreta los datos. "
        "No autorices cambios productivos ni prometas retornos. Prioriza PnL neto, costos, profit factor, cola de perdidas y muestra. "
        "Devuelve JSON con conclusion, risks, proposed_candidate_ids y evidence.\n"
        + json.dumps(rows, default=str, ensure_ascii=True)
    )
    ai_text = None
    if config.get("openai_api_key"):
        from openai import OpenAI
        ai_text = OpenAI(api_key=config["openai_api_key"], timeout=90).responses.create(model=config["openai_model"], input=prompt).output_text
    selected = [{"candidate_id": row["candidate_id"], "strategy_version": row["strategy_version"]} for row in eligible]
    errors = client.insert_rows_json(config["audits_table"], [{
        "run_id": run_id, "created_at": datetime.utcnow().isoformat(),
        "audit_status": "PROPOSED_FOR_BACKTEST_REVIEW" if eligible else "NO_ELIGIBLE_CANDIDATE",
        "selected_candidates_json": json.dumps(selected), "evidence_json": json.dumps(rows, default=str),
        "ai_interpretation": ai_text, "model_name": config.get("openai_model"), "production_change_allowed": False,
    }])
    if errors:
        raise RuntimeError(f"Could not save audit: {errors}")
    client.query(
        f"UPDATE `{config['runs_table']}` SET status = 'REVIEWED' WHERE run_id = @run_id",
        job_config=bigquery.QueryJobConfig(
            query_parameters=[bigquery.ScalarQueryParameter("run_id", "STRING", run_id)]
        ),
    ).result()
    return {"run_id": run_id, "status": "REVIEW_SAVED", "eligible_count": len(eligible), "production_change_allowed": False, "results": rows}


def main(request):
    payload = request.get_json(silent=True) or {}
    phase = payload.get("phase", "generate").lower()
    if phase not in {"generate", "review"}:
        return json.dumps({"status": "error", "message": "phase must be generate or review"}), 400, {"Content-Type": "application/json"}
    try:
        config = load_config()
        client = bigquery.Client(project=config["project_id"])
        for statement in _table_ddl(config):
            client.query(statement).result()
        result = _generate(client, config, payload) if phase == "generate" else _review(client, config, payload)
        return json.dumps(result, default=str), 200, {"Content-Type": "application/json"}
    except Exception as exc:
        logging.exception("strategy brain failed")
        return json.dumps({"status": "error", "message": str(exc)}), 500, {"Content-Type": "application/json"}


if __name__ == "__main__":
    from functions_framework import create_app

    port = int(os.environ.get("PORT", 8080))
    app = create_app("main")
    app.run(host="0.0.0.0", port=port)

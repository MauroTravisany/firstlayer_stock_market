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
          data_quality_notes STRING, production_change_allowed BOOL NOT NULL,
          generation INT64, parent_run_id STRING, generation_policy STRING
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
          created_at TIMESTAMP NOT NULL, generation INT64, parent_candidate_id STRING
        ) CLUSTER BY run_id, candidate_status
        """,
        f"""
        CREATE TABLE IF NOT EXISTS `{config['audits_table']}` (
          run_id STRING NOT NULL, created_at TIMESTAMP NOT NULL, audit_status STRING NOT NULL,
          selected_candidates_json STRING NOT NULL, evidence_json STRING NOT NULL,
          ai_interpretation STRING, model_name STRING, production_change_allowed BOOL NOT NULL
        ) CLUSTER BY run_id, audit_status
        """,
        f"ALTER TABLE `{config['runs_table']}` ADD COLUMN IF NOT EXISTS generation INT64",
        f"ALTER TABLE `{config['runs_table']}` ADD COLUMN IF NOT EXISTS parent_run_id STRING",
        f"ALTER TABLE `{config['runs_table']}` ADD COLUMN IF NOT EXISTS generation_policy STRING",
        f"ALTER TABLE `{config['candidates_table']}` ADD COLUMN IF NOT EXISTS generation INT64",
        f"ALTER TABLE `{config['candidates_table']}` ADD COLUMN IF NOT EXISTS parent_candidate_id STRING",
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


def _candidate_rows(run_id, baseline, windows, generation=1, parent_candidate_id=None):
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
            "generation": generation,
            "parent_candidate_id": parent_candidate_id,
        })
    return records


def _clamp_weights(weights):
    bounded = dict(weights)
    for field in WEIGHT_FIELDS:
        bounded[field] = round(max(-1.5, min(1.5, float(bounded[field]))), 2)
    bounded["min_trade_score_add"] = round(max(-0.5, min(1.0, float(bounded["min_trade_score_add"]))), 2)
    bounded["position_size_multiplier"] = round(max(0.5, min(1.1, float(bounded["position_size_multiplier"]))), 2)
    return bounded


def _parent_candidates(client, config):
    query = f"""
      WITH audited_runs AS (
        SELECT DISTINCT run_id
        FROM `{config['audits_table']}`
      ), scored AS (
        SELECT
          c.*,
          AVG(s.profit_factor) AS avg_profit_factor,
          AVG(s.avg_net_return_pct) AS avg_net_return_pct,
          AVG(s.win_rate_pct) AS avg_win_rate_pct,
          AVG(s.pnl_p05_clp) AS avg_pnl_p05_clp,
          SUM(s.net_pnl_clp) AS total_net_pnl_clp,
          SUM(s.closed_trades) AS total_closed_trades
        FROM `{config['candidates_table']}` c
        JOIN `{config['summary_table']}` s
          USING (run_id, candidate_id)
        JOIN audited_runs a USING (run_id)
        WHERE s.evaluation_split = "VALIDATION"
        GROUP BY c.run_id, c.candidate_id, c.candidate_status, c.formula_version,
          c.candidate_label, c.candidate_reason, c.training_start, c.training_end,
          c.validation_start, c.validation_end, c.fear_weight, c.monetary_weight,
          c.earnings_weight, c.company_lifecycle_weight, c.quality_weight,
          c.valuation_state_weight, c.political_risk_weight, c.crypto_cycle_weight,
          c.min_trade_score_add, c.position_size_multiplier, c.formula_expression,
          c.created_at, c.generation, c.parent_candidate_id
      )
      SELECT *
      FROM scored
      WHERE total_closed_trades >= 80
      ORDER BY
        avg_profit_factor DESC,
        avg_net_return_pct DESC,
        avg_pnl_p05_clp DESC,
        avg_win_rate_pct DESC,
        total_net_pnl_clp DESC
      LIMIT 3
    """
    return [dict(row.items()) for row in client.query(query).result()]


def _iterative_candidate_rows(run_id, parents, windows, generation):
    candidates = []
    templates = (
        ("anchor", "Replica del mejor candidato", "Control local para medir si la siguiente generacion mejora al padre.", {}),
        ("risk_down", "Reducir riesgo desde el padre", "Reduce exposicion sin cambiar el filtro de entrada.", {"position_size_multiplier": -0.10}),
        ("threshold_up", "Filtro mas estricto", "Exige mayor calidad de setup y reduce levemente exposicion.", {"min_trade_score_add": 0.15, "position_size_multiplier": -0.05}),
        ("threshold_down", "Filtro moderadamente flexible", "Explora mas oportunidades con exposicion prudente.", {"min_trade_score_add": -0.10, "position_size_multiplier": -0.10}),
        ("quality_defensive", "Calidad defensiva", "Refuerza calidad, valoracion y proteccion ante miedo o riesgo politico.", {"quality_weight": 0.15, "valuation_state_weight": 0.15, "fear_weight": 0.15, "political_risk_weight": 0.15, "position_size_multiplier": -0.10}),
        ("event_careful", "Cautela ante eventos", "Aumenta sensibilidad a earnings y condiciones monetarias.", {"earnings_weight": 0.15, "monetary_weight": 0.15, "position_size_multiplier": -0.05}),
    )
    for parent in parents:
        seed = {field: float(parent[field]) for field in WEIGHT_FIELDS}
        seed["min_trade_score_add"] = float(parent["min_trade_score_add"])
        seed["position_size_multiplier"] = float(parent["position_size_multiplier"])
        for suffix, label, reason, deltas in templates:
            weights = dict(seed)
            for field, delta in deltas.items():
                weights[field] = weights[field] + delta
            weights = _clamp_weights(weights)
            candidate_id = f"brain_g{generation}_{run_id.replace('-', '')[:10]}_{parent['candidate_id'][-12:]}_{suffix}"
            candidates.append({
                "run_id": run_id,
                "candidate_id": candidate_id,
                "candidate_status": "BACKTEST_ONLY",
                "formula_version": FORMULA_VERSION,
                "candidate_label": f"G{generation}: {label}",
                "candidate_reason": f"Padre={parent['candidate_id']}; {reason}",
                **{key: value.isoformat() for key, value in windows.items()},
                **weights,
                "formula_expression": _formula_expression(weights),
                "created_at": datetime.utcnow().isoformat(),
                "generation": generation,
                "parent_candidate_id": parent["candidate_id"],
            })
    return candidates


def _generate(client, config, payload):
    training_start = _parse_date(payload.get("training_start", "2019-01-01"), "training_start")
    training_end = _parse_date(payload.get("training_end", "2024-12-31"), "training_end")
    validation_start = _parse_date(payload.get("validation_start", "2025-01-01"), "validation_start")
    validation_end = _parse_date(payload.get("validation_end", str(date.today() - timedelta(days=1))), "validation_end")
    if not training_start <= training_end < validation_start <= validation_end:
        raise ValueError("Require training_start <= training_end < validation_start <= validation_end")

    run_id = payload.get("run_id") or f"brain-{datetime.utcnow():%Y%m%d%H%M%S}-{uuid.uuid4().hex[:6]}"
    windows = {"training_start": training_start, "training_end": training_end, "validation_start": validation_start, "validation_end": validation_end}
    parents = _parent_candidates(client, config)
    if parents:
        generation = max(int(parent.get("generation") or 1) for parent in parents) + 1
        parent_run_id = parents[0]["run_id"]
        generation_policy = "Iterative local search around the three best audited validation candidates."
        candidates = _iterative_candidate_rows(run_id, parents, windows, generation)
    else:
        baseline = _baseline(client, config)
        generation = 1
        parent_run_id = None
        generation_policy = "Initial bounded exploration around the current baseline."
        candidates = _candidate_rows(run_id, baseline, windows, generation=generation)
    objective = "Rank validation candidates by profit factor, average net return after costs, p05 tail loss, win rate and net PnL. Never promote to production."
    run_errors = client.insert_rows_json(config["runs_table"], [{
        "run_id": run_id, "created_at": datetime.utcnow().isoformat(), "status": "CANDIDATES_READY",
        "formula_version": FORMULA_VERSION, **{key: value.isoformat() for key, value in windows.items()}, "objective_definition": objective,
        "data_quality_notes": "Daily price history is broad; earnings/news/macro historical coverage must be audited before interpretation.",
        "production_change_allowed": False, "generation": generation, "parent_run_id": parent_run_id,
        "generation_policy": generation_policy,
    }])
    if run_errors:
        raise RuntimeError(f"Could not save run: {run_errors}")
    errors = client.insert_rows_json(config["candidates_table"], candidates)
    if errors:
        raise RuntimeError(f"Could not save candidates: {errors}")
    return {"run_id": run_id, "generation": generation, "parent_run_id": parent_run_id, "candidate_count": len(candidates), "status": "CANDIDATES_READY", "next_step": "Run Dataform, then call phase=review with this run_id."}


def _review(client, config, payload):
    run_id = payload.get("run_id")
    if not run_id:
        latest = list(client.query(
            f"""
            SELECT r.run_id
            FROM `{config['runs_table']}` r
            WHERE r.status = 'CANDIDATES_READY'
              AND NOT EXISTS (
                SELECT 1 FROM `{config['audits_table']}` a WHERE a.run_id = r.run_id
              )
            ORDER BY r.created_at DESC
            LIMIT 1
            """
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

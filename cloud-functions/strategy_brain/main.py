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

FORMULA_VERSION = "brain-group-context-v2"
INITIAL_CAPITAL_CLP = 10_000_000
MAX_GENERATIONS = 4
MAX_CONSECUTIVE_NON_IMPROVING_GENERATIONS = 2
MIN_MATERIAL_RETURN_IMPROVEMENT_PCT = 2.0
MAX_CANDIDATES_PER_GENERATION = 12
MIN_VALIDATION_TRADES = 10
WEIGHT_FIELDS = (
    "trend_weight",
    "momentum_weight",
    "volume_weight",
    "volatility_weight",
    "regime_weight",
    "fear_weight",
    "monetary_weight",
    "earnings_weight",
    "company_lifecycle_weight",
    "quality_weight",
    "valuation_state_weight",
    "political_risk_weight",
    "crypto_cycle_weight",
)

ASSET_SCOPES = {
    "MEGACAP_TECH": {
        "tickers": ("AAPL", "META"),
        "strategy_version": "v2",
        "description": "Megacaps tecnologicas: AAPL y META con la estrategia V2.",
    },
}


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
          generation INT64, parent_run_id STRING, generation_policy STRING,
          asset_scope STRING, target_strategy_version STRING
        ) CLUSTER BY status, formula_version
        """,
        f"""
        CREATE TABLE IF NOT EXISTS `{config['candidates_table']}` (
          run_id STRING NOT NULL, candidate_id STRING NOT NULL, candidate_status STRING NOT NULL,
          formula_version STRING NOT NULL, candidate_label STRING NOT NULL, candidate_reason STRING NOT NULL,
          training_start DATE NOT NULL, training_end DATE NOT NULL, validation_start DATE NOT NULL, validation_end DATE NOT NULL,
          fear_weight FLOAT64 NOT NULL, monetary_weight FLOAT64 NOT NULL, earnings_weight FLOAT64 NOT NULL,
          trend_weight FLOAT64, momentum_weight FLOAT64, volume_weight FLOAT64, volatility_weight FLOAT64, regime_weight FLOAT64,
          company_lifecycle_weight FLOAT64 NOT NULL, quality_weight FLOAT64 NOT NULL,
          valuation_state_weight FLOAT64 NOT NULL, political_risk_weight FLOAT64 NOT NULL,
          crypto_cycle_weight FLOAT64 NOT NULL, min_trade_score_add FLOAT64 NOT NULL,
          position_size_multiplier FLOAT64 NOT NULL, formula_expression STRING NOT NULL,
          created_at TIMESTAMP NOT NULL, generation INT64, parent_candidate_id STRING,
          asset_scope STRING, asset_tickers ARRAY<STRING>, target_strategy_version STRING
        ) CLUSTER BY run_id, candidate_status
        """,
        f"""
        CREATE TABLE IF NOT EXISTS `{config['audits_table']}` (
          run_id STRING NOT NULL, created_at TIMESTAMP NOT NULL, audit_status STRING NOT NULL,
          selected_candidates_json STRING NOT NULL, evidence_json STRING NOT NULL,
          ai_interpretation STRING, model_name STRING, production_change_allowed BOOL NOT NULL,
          generation INT64, generation_outcome STRING, material_improvement BOOL,
          best_validation_score FLOAT64, convergence_reason STRING, promotion_recommendation STRING,
          asset_scope STRING, target_strategy_version STRING
        ) CLUSTER BY run_id, audit_status
        """,
        f"ALTER TABLE `{config['runs_table']}` ADD COLUMN IF NOT EXISTS generation INT64",
        f"ALTER TABLE `{config['runs_table']}` ADD COLUMN IF NOT EXISTS parent_run_id STRING",
        f"ALTER TABLE `{config['runs_table']}` ADD COLUMN IF NOT EXISTS generation_policy STRING",
        f"ALTER TABLE `{config['runs_table']}` ADD COLUMN IF NOT EXISTS asset_scope STRING",
        f"ALTER TABLE `{config['runs_table']}` ADD COLUMN IF NOT EXISTS target_strategy_version STRING",
        f"ALTER TABLE `{config['candidates_table']}` ADD COLUMN IF NOT EXISTS generation INT64",
        f"ALTER TABLE `{config['candidates_table']}` ADD COLUMN IF NOT EXISTS parent_candidate_id STRING",
        f"ALTER TABLE `{config['candidates_table']}` ADD COLUMN IF NOT EXISTS trend_weight FLOAT64",
        f"ALTER TABLE `{config['candidates_table']}` ADD COLUMN IF NOT EXISTS momentum_weight FLOAT64",
        f"ALTER TABLE `{config['candidates_table']}` ADD COLUMN IF NOT EXISTS volume_weight FLOAT64",
        f"ALTER TABLE `{config['candidates_table']}` ADD COLUMN IF NOT EXISTS volatility_weight FLOAT64",
        f"ALTER TABLE `{config['candidates_table']}` ADD COLUMN IF NOT EXISTS regime_weight FLOAT64",
        f"ALTER TABLE `{config['candidates_table']}` ADD COLUMN IF NOT EXISTS asset_scope STRING",
        f"ALTER TABLE `{config['candidates_table']}` ADD COLUMN IF NOT EXISTS asset_tickers ARRAY<STRING>",
        f"ALTER TABLE `{config['candidates_table']}` ADD COLUMN IF NOT EXISTS target_strategy_version STRING",
        f"ALTER TABLE `{config['audits_table']}` ADD COLUMN IF NOT EXISTS generation INT64",
        f"ALTER TABLE `{config['audits_table']}` ADD COLUMN IF NOT EXISTS generation_outcome STRING",
        f"ALTER TABLE `{config['audits_table']}` ADD COLUMN IF NOT EXISTS material_improvement BOOL",
        f"ALTER TABLE `{config['audits_table']}` ADD COLUMN IF NOT EXISTS best_validation_score FLOAT64",
        f"ALTER TABLE `{config['audits_table']}` ADD COLUMN IF NOT EXISTS convergence_reason STRING",
        f"ALTER TABLE `{config['audits_table']}` ADD COLUMN IF NOT EXISTS promotion_recommendation STRING",
        f"ALTER TABLE `{config['audits_table']}` ADD COLUMN IF NOT EXISTS asset_scope STRING",
        f"ALTER TABLE `{config['audits_table']}` ADD COLUMN IF NOT EXISTS target_strategy_version STRING",
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
    technical_terms = " + ".join(
        f"{field}*{field.replace('_weight', '_score')}" for field in WEIGHT_FIELDS[:5]
    )
    context_terms = " + ".join(
        f"{field}*{field.replace('_weight', '_component')}" for field in WEIGHT_FIELDS[5:]
    )
    return (
        "contextual_setup_score = technical(" + technical_terms + ") + macro + factors + earnings + "
        f"context({context_terms}); threshold = min_trade_score + {weights['min_trade_score_add']}; "
        f"position_notional = base_position_notional * {weights['position_size_multiplier']}; "
        "net_pnl = position_notional * (gross_return - estimated_roundtrip_cost_pct / 100)"
    )


def _scope_definition(payload):
    asset_scope = str(payload.get("asset_scope") or "MEGACAP_TECH").upper()
    scope = ASSET_SCOPES.get(asset_scope)
    if not scope:
        raise ValueError(f"asset_scope must be one of: {', '.join(sorted(ASSET_SCOPES))}")
    return asset_scope, scope


def _candidate_rows(run_id, baseline, windows, scope_name, scope, generation=1, parent_candidate_id=None):
    candidates = [("baseline", "Control sin cambio", "Control para comparar cambios de pesos.", {})]
    for field in WEIGHT_FIELDS[:5]:
        candidates.append((f"{field}_down", f"Reducir {field}", "Prueba local de sensibilidad tecnica.", {field: round(float(baseline[field]) - 0.15, 2)}))
        candidates.append((f"{field}_up", f"Aumentar {field}", "Prueba local de sensibilidad tecnica.", {field: round(float(baseline[field]) + 0.15, 2)}))
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
            "asset_scope": scope_name,
            "asset_tickers": list(scope["tickers"]),
            "target_strategy_version": scope["strategy_version"],
        })
    return records[:MAX_CANDIDATES_PER_GENERATION]


def _clamp_weights(weights):
    bounded = dict(weights)
    for field in WEIGHT_FIELDS[:5]:
        bounded[field] = round(max(0.25, min(2.0, float(bounded[field]))), 2)
    for field in WEIGHT_FIELDS[5:]:
        bounded[field] = round(max(-1.5, min(1.5, float(bounded[field]))), 2)
    bounded["min_trade_score_add"] = round(max(-0.5, min(1.0, float(bounded["min_trade_score_add"]))), 2)
    bounded["position_size_multiplier"] = round(max(0.5, min(1.1, float(bounded["position_size_multiplier"]))), 2)
    return bounded


def _parent_candidates(client, config, asset_scope, target_strategy_version, parent_run_id=None):
    query = f"""
      WITH audited_runs AS (
        SELECT DISTINCT run_id
        FROM `{config['audits_table']}`
      ), scored AS (
        SELECT
          c.*,
          s.profit_factor AS avg_profit_factor,
          s.avg_net_return_pct,
          s.win_rate_pct AS avg_win_rate_pct,
          s.pnl_p05_clp AS avg_pnl_p05_clp,
          s.net_pnl_clp AS total_net_pnl_clp,
          s.closed_trades AS total_closed_trades,
          s.final_return_pct AS avg_final_return_pct,
          s.final_capital_clp AS avg_final_capital_clp,
          s.max_drawdown_pct AS worst_max_drawdown_pct
        FROM `{config['candidates_table']}` c
        JOIN `{config['summary_table']}` s
          USING (run_id, candidate_id)
        JOIN audited_runs a USING (run_id)
        WHERE s.evaluation_split = "VALIDATION"
          AND c.asset_scope = @asset_scope
          AND c.target_strategy_version = @target_strategy_version
          AND s.strategy_version = c.target_strategy_version
          AND (@parent_run_id IS NULL OR c.run_id = @parent_run_id)
        GROUP BY c.run_id, c.candidate_id, c.candidate_status, c.formula_version,
          c.candidate_label, c.candidate_reason, c.training_start, c.training_end,
          c.validation_start, c.validation_end, c.fear_weight, c.monetary_weight,
          c.earnings_weight, c.trend_weight, c.momentum_weight, c.volume_weight,
          c.volatility_weight, c.regime_weight, c.company_lifecycle_weight, c.quality_weight,
          c.valuation_state_weight, c.political_risk_weight, c.crypto_cycle_weight,
          c.min_trade_score_add, c.position_size_multiplier, c.formula_expression,
          c.created_at, c.generation, c.parent_candidate_id, c.asset_scope,
          c.asset_tickers, c.target_strategy_version, s.profit_factor,
          s.avg_net_return_pct, s.win_rate_pct, s.pnl_p05_clp, s.net_pnl_clp,
          s.closed_trades, s.final_return_pct, s.final_capital_clp, s.max_drawdown_pct
      )
      SELECT *
      FROM scored
      WHERE total_closed_trades >= @min_validation_trades
      ORDER BY
        avg_final_return_pct DESC,
        worst_max_drawdown_pct ASC,
        avg_profit_factor DESC,
        avg_net_return_pct DESC,
        avg_pnl_p05_clp DESC,
        avg_win_rate_pct DESC,
        total_net_pnl_clp DESC
      LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("parent_run_id", "STRING", parent_run_id),
        bigquery.ScalarQueryParameter("asset_scope", "STRING", asset_scope),
        bigquery.ScalarQueryParameter("target_strategy_version", "STRING", target_strategy_version),
        bigquery.ScalarQueryParameter("min_validation_trades", "INT64", MIN_VALIDATION_TRADES),
    ])
    return [dict(row.items()) for row in client.query(query, job_config=job_config).result()]


def _optimization_state(client, config, asset_scope, exclude_run_id=None):
    """Read only completed audit rows; never infer convergence from an unfinished run."""
    query = f"""
      WITH latest_audit_per_generation AS (
        SELECT
          run_id,
          generation,
          ARRAY_AGG(generation_outcome IGNORE NULLS ORDER BY created_at DESC LIMIT 1)[SAFE_OFFSET(0)] AS generation_outcome
        FROM `{config['audits_table']}`
        WHERE generation IS NOT NULL
          AND asset_scope = @asset_scope
          AND (@exclude_run_id IS NULL OR run_id != @exclude_run_id)
        GROUP BY run_id, generation
      )
      SELECT
        MAX(generation) AS latest_generation,
        COUNTIF(generation_outcome = 'NO_MATERIAL_IMPROVEMENT') AS non_improving_generations,
        ARRAY_AGG(generation_outcome IGNORE NULLS ORDER BY generation DESC LIMIT 2) AS latest_outcomes
      FROM latest_audit_per_generation
    """
    rows = list(client.query(
        query,
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("asset_scope", "STRING", asset_scope),
            bigquery.ScalarQueryParameter("exclude_run_id", "STRING", exclude_run_id),
        ]),
    ).result())
    if not rows:
        return {"latest_generation": 0, "consecutive_non_improving": 0}
    row = dict(rows[0].items())
    outcomes = row.get("latest_outcomes") or []
    consecutive = 0
    for outcome in outcomes:
        if outcome == "NO_MATERIAL_IMPROVEMENT":
            consecutive += 1
        else:
            break
    return {
        "latest_generation": int(row.get("latest_generation") or 0),
        "consecutive_non_improving": consecutive,
    }


def _iterative_candidate_rows(run_id, parents, windows, scope_name, scope, generation):
    candidates = []
    templates = (
        ("anchor", "Replica del mejor candidato", "Control local para medir si la siguiente generacion mejora al padre.", {}),
        ("risk_down", "Reducir riesgo desde el padre", "Reduce exposicion sin cambiar el filtro de entrada.", {"position_size_multiplier": -0.10}),
        ("threshold_up", "Filtro mas estricto", "Exige mayor calidad de setup y reduce levemente exposicion.", {"min_trade_score_add": 0.15, "position_size_multiplier": -0.05}),
        ("threshold_down", "Filtro moderadamente flexible", "Explora mas oportunidades con exposicion prudente.", {"min_trade_score_add": -0.10, "position_size_multiplier": -0.10}),
        ("quality_defensive", "Calidad defensiva", "Refuerza calidad, valoracion y proteccion ante miedo o riesgo politico.", {"quality_weight": 0.15, "valuation_state_weight": 0.15, "fear_weight": 0.15, "political_risk_weight": 0.15, "position_size_multiplier": -0.10}),
        ("event_careful", "Cautela ante eventos", "Aumenta sensibilidad a earnings y condiciones monetarias.", {"earnings_weight": 0.15, "monetary_weight": 0.15, "position_size_multiplier": -0.05}),
        ("trend_confirmed", "Tendencia confirmada", "Da mayor importancia a tendencia, momentum y volumen, manteniendo riesgo prudente.", {"trend_weight": 0.15, "momentum_weight": 0.15, "volume_weight": 0.10, "position_size_multiplier": -0.05}),
        ("trend_defensive", "Tendencia defensiva", "Reduce entradas por volatilidad y exige una tendencia mas limpia.", {"trend_weight": 0.15, "volatility_weight": -0.10, "regime_weight": 0.10, "min_trade_score_add": 0.10, "position_size_multiplier": -0.05}),
        ("trend_quality", "Tendencia con calidad", "Combina tendencia, momentum, calidad y valoracion para evitar persecucion de precio sin respaldo.", {"trend_weight": 0.20, "momentum_weight": 0.10, "quality_weight": 0.15, "valuation_state_weight": 0.15, "min_trade_score_add": 0.05, "position_size_multiplier": -0.05}),
        ("trend_regime", "Tendencia segun regimen", "Refuerza tendencia solo cuando el regimen y volatilidad son favorables.", {"trend_weight": 0.20, "regime_weight": 0.15, "volatility_weight": -0.15, "volume_weight": 0.10, "min_trade_score_add": 0.10, "position_size_multiplier": -0.05}),
        ("selective_events", "Selectivo ante eventos", "Prioriza tendencia pero reduce entradas alrededor de incertidumbre macro y resultados.", {"trend_weight": 0.15, "earnings_weight": 0.20, "fear_weight": 0.15, "monetary_weight": 0.10, "min_trade_score_add": 0.15, "position_size_multiplier": -0.10}),
    )
    for parent in parents:
        seed = {
            field: float(parent.get(field) if parent.get(field) is not None else (1.0 if field in WEIGHT_FIELDS[:5] else 0.0))
            for field in WEIGHT_FIELDS
        }
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
                "asset_scope": scope_name,
                "asset_tickers": list(scope["tickers"]),
                "target_strategy_version": scope["strategy_version"],
            })
    return candidates[:MAX_CANDIDATES_PER_GENERATION]


def _generate(client, config, payload):
    training_start = _parse_date(payload.get("training_start", "2019-01-01"), "training_start")
    training_end = _parse_date(payload.get("training_end", "2024-12-31"), "training_end")
    validation_start = _parse_date(payload.get("validation_start", "2025-01-01"), "validation_start")
    validation_end = _parse_date(payload.get("validation_end", str(date.today() - timedelta(days=1))), "validation_end")
    if not training_start <= training_end < validation_start <= validation_end:
        raise ValueError("Require training_start <= training_end < validation_start <= validation_end")

    asset_scope, scope = _scope_definition(payload)
    run_id = payload.get("run_id") or f"brain-{datetime.utcnow():%Y%m%d%H%M%S}-{uuid.uuid4().hex[:6]}"
    windows = {"training_start": training_start, "training_end": training_end, "validation_start": validation_start, "validation_end": validation_end}
    optimization = _optimization_state(client, config, asset_scope)
    if not payload.get("force") and (
        optimization["latest_generation"] >= MAX_GENERATIONS
        or optimization["consecutive_non_improving"] >= MAX_CONSECUTIVE_NON_IMPROVING_GENERATIONS
    ):
        return {
            "status": "CONVERGED",
            "next_step": "Review the promotion recommendation; do not create more variants without new data or a changed hypothesis.",
            "latest_generation": optimization["latest_generation"],
            "consecutive_non_improving": optimization["consecutive_non_improving"],
        }
    requested_parent_run_id = payload.get("parent_run_id")
    parents = _parent_candidates(client, config, asset_scope, scope["strategy_version"], requested_parent_run_id)
    if parents:
        generation = int(payload.get("generation_override") or (max(int(parent.get("generation") or 1) for parent in parents) + 1))
        parent_run_id = requested_parent_run_id or parents[0]["run_id"]
        generation_policy = (
            "Forced hypothesis retest around audited parents from the requested run."
            if requested_parent_run_id else
            "Iterative local search around the best audited candidate in the selected asset group."
        )
        candidates = _iterative_candidate_rows(run_id, parents, windows, asset_scope, scope, generation)
    else:
        baseline = _baseline(client, config)
        generation = 1
        parent_run_id = None
        generation_policy = "Initial bounded exploration of twelve local variants for one asset group."
        candidates = _candidate_rows(run_id, baseline, windows, asset_scope, scope, generation=generation)
    objective = (
        f"For {asset_scope} ({', '.join(scope['tickers'])}) using {scope['strategy_version']}, simulate a separate "
        "sequential one-slot CLP 10,000,000 portfolio. Maximize validated final capital after costs while reducing "
        "maximum drawdown and tail loss. Test at most twelve candidates per generation, stop after two non-material "
        "generations or four total generations, and never auto-promote to production."
    )
    run_errors = client.insert_rows_json(config["runs_table"], [{
        "run_id": run_id, "created_at": datetime.utcnow().isoformat(), "status": "CANDIDATES_READY",
        "formula_version": FORMULA_VERSION, **{key: value.isoformat() for key, value in windows.items()}, "objective_definition": objective,
        "data_quality_notes": "The pilot is scoped to one asset group and one strategy. It uses CLP 10,000,000, one sequential position, fixed bounded notional and daily prices. Historical news coverage remains limited and is not optimized.",
        "production_change_allowed": False, "generation": generation, "parent_run_id": parent_run_id,
        "generation_policy": generation_policy, "asset_scope": asset_scope,
        "target_strategy_version": scope["strategy_version"],
    }])
    if run_errors:
        raise RuntimeError(f"Could not save run: {run_errors}")
    errors = client.insert_rows_json(config["candidates_table"], candidates)
    if errors:
        raise RuntimeError(f"Could not save candidates: {errors}")
    return {"run_id": run_id, "generation": generation, "parent_run_id": parent_run_id, "asset_scope": asset_scope, "tickers": scope["tickers"], "strategy_version": scope["strategy_version"], "candidate_count": len(candidates), "status": "CANDIDATES_READY", "capital_per_strategy_clp": INITIAL_CAPITAL_CLP, "next_step": "Run the brain Dataform targets, then call phase=review once for this run."}


def _validation_candidate_scores(client, config, run_id):
    """Score the target strategy inside one asset scope; never mix portfolios."""
    query = f"""
      SELECT
        s.run_id,
        s.candidate_id,
        ANY_VALUE(c.candidate_label) AS candidate_label,
        ANY_VALUE(c.generation) AS generation,
        ANY_VALUE(c.asset_scope) AS asset_scope,
        ANY_VALUE(c.target_strategy_version) AS target_strategy_version,
        ANY_VALUE(s.mechanical_verdict) AS mechanical_verdict,
        MAX(s.ticker_count) AS ticker_count,
        SUM(s.closed_trades) AS total_closed_trades,
        ROUND(AVG(s.final_return_pct), 2) AS avg_final_return_pct,
        ROUND(AVG(s.final_capital_clp), 0) AS avg_final_capital_clp,
        ROUND(SUM(s.net_pnl_clp), 0) AS total_net_pnl_clp,
        ROUND(AVG(s.profit_factor), 3) AS avg_profit_factor,
        ROUND(AVG(s.win_rate_pct), 2) AS avg_win_rate_pct,
        ROUND(MAX(s.max_drawdown_pct), 2) AS worst_max_drawdown_pct,
        ROUND(MIN(s.pnl_p05_clp), 0) AS worst_pnl_p05_clp,
        ROUND(
          AVG(s.final_return_pct)
          - 0.75 * MAX(s.max_drawdown_pct)
          + 5 * LEAST(AVG(s.profit_factor) - 1, 1)
          + 0.05 * (AVG(s.win_rate_pct) - 45),
          4
        ) AS risk_adjusted_score
      FROM `{config['summary_table']}` s
      JOIN `{config['candidates_table']}` c USING (run_id, candidate_id)
      WHERE s.run_id = @run_id
        AND s.evaluation_split = "VALIDATION"
        AND s.strategy_version = c.target_strategy_version
      GROUP BY s.run_id, s.candidate_id
      ORDER BY risk_adjusted_score DESC, avg_final_return_pct DESC, worst_max_drawdown_pct ASC
    """
    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("run_id", "STRING", run_id)
    ])
    return [dict(row.items()) for row in client.query(query, job_config=job_config).result()]


def _previous_best_score(client, config, run_id, asset_scope, target_strategy_version):
    query = f"""
      WITH audited AS (
        SELECT DISTINCT run_id FROM `{config['audits_table']}` WHERE run_id != @run_id
      ), scored AS (
        SELECT
          s.run_id,
          s.candidate_id,
          AVG(s.final_return_pct) AS avg_final_return_pct,
          AVG(s.profit_factor) AS avg_profit_factor,
          AVG(s.win_rate_pct) AS avg_win_rate_pct,
          MAX(s.max_drawdown_pct) AS worst_max_drawdown_pct,
          AVG(s.final_return_pct)
            - 0.75 * MAX(s.max_drawdown_pct)
            + 5 * LEAST(AVG(s.profit_factor) - 1, 1)
            + 0.05 * (AVG(s.win_rate_pct) - 45) AS risk_adjusted_score
        FROM `{config['summary_table']}` s
        JOIN audited a USING (run_id)
        JOIN `{config['candidates_table']}` c USING (run_id, candidate_id)
        WHERE s.evaluation_split = "VALIDATION"
          AND c.asset_scope = @asset_scope
          AND c.target_strategy_version = @target_strategy_version
          AND s.strategy_version = c.target_strategy_version
        GROUP BY s.run_id, s.candidate_id
      )
      SELECT * FROM scored
      ORDER BY risk_adjusted_score DESC
      LIMIT 1
    """
    job_config = bigquery.QueryJobConfig(query_parameters=[
        bigquery.ScalarQueryParameter("run_id", "STRING", run_id),
        bigquery.ScalarQueryParameter("asset_scope", "STRING", asset_scope),
        bigquery.ScalarQueryParameter("target_strategy_version", "STRING", target_strategy_version),
    ])
    rows = list(client.query(query, job_config=job_config).result())
    return dict(rows[0].items()) if rows else None


def _review(client, config, payload):
    run_id = payload.get("run_id")
    requested_scope, requested_scope_definition = _scope_definition(payload)
    if not run_id:
        latest = list(client.query(
            f"""
            SELECT r.run_id
            FROM `{config['runs_table']}` r
            WHERE r.status = 'CANDIDATES_READY'
              AND r.asset_scope = @asset_scope
              AND NOT EXISTS (
                SELECT 1 FROM `{config['audits_table']}` a WHERE a.run_id = r.run_id
              )
            ORDER BY r.created_at DESC
            LIMIT 1
            """,
            job_config=bigquery.QueryJobConfig(query_parameters=[
                bigquery.ScalarQueryParameter("asset_scope", "STRING", requested_scope)
            ])
        ).result())
        if not latest:
            raise ValueError("run_id is required when no candidate run exists")
        run_id = latest[0]["run_id"]
    scope_rows = list(client.query(
        f"""
        SELECT asset_scope, target_strategy_version
        FROM `{config['candidates_table']}`
        WHERE run_id = @run_id
        QUALIFY ROW_NUMBER() OVER (ORDER BY created_at) = 1
        """,
        job_config=bigquery.QueryJobConfig(query_parameters=[
            bigquery.ScalarQueryParameter("run_id", "STRING", run_id)
        ])
    ).result())
    if not scope_rows or not scope_rows[0]["asset_scope"]:
        raise ValueError("This run has no asset scope. Generate a new scoped run before reviewing it.")
    asset_scope = scope_rows[0]["asset_scope"]
    target_strategy_version = scope_rows[0]["target_strategy_version"]
    scope = ASSET_SCOPES.get(asset_scope, requested_scope_definition)
    query = f"""
      SELECT * FROM `{config['summary_table']}`
      WHERE run_id = @run_id AND evaluation_split = 'VALIDATION'
      ORDER BY strategy_version, mechanical_verdict DESC, net_pnl_clp DESC
    """
    rows = [dict(row.items()) for row in client.query(query, job_config=bigquery.QueryJobConfig(query_parameters=[bigquery.ScalarQueryParameter("run_id", "STRING", run_id)])).result()]
    if not rows:
        raise RuntimeError("No validation summary exists yet. Run Dataform after generating candidates.")
    candidates = _validation_candidate_scores(client, config, run_id)
    if not candidates:
        raise RuntimeError("No candidate capital curves exist yet. Run Dataform after generating candidates.")
    best = candidates[0]
    eligible = [candidate for candidate in candidates if (
        candidate["mechanical_verdict"] == "ELIGIBLE_FOR_REVIEW"
        and candidate["total_closed_trades"] >= MIN_VALIDATION_TRADES
        and candidate["avg_final_return_pct"] > 0
        and candidate["avg_profit_factor"] >= 1.10
        and candidate["worst_max_drawdown_pct"] <= 12
        and candidate["worst_pnl_p05_clp"] > -250000
    )]
    previous_best = _previous_best_score(client, config, run_id, asset_scope, target_strategy_version)
    current_generation = int(best.get("generation") or 1)
    reference = previous_best
    if reference is None:
        reference = next((item for item in candidates if item["candidate_id"].endswith("_baseline")), None)
    material_improvement = bool(eligible) and (
        reference is None or (
            best["risk_adjusted_score"] >= reference["risk_adjusted_score"] + MIN_MATERIAL_RETURN_IMPROVEMENT_PCT
            and best["worst_max_drawdown_pct"] <= reference["worst_max_drawdown_pct"] + 0.25
        )
    )
    outcome = "MATERIAL_IMPROVEMENT" if material_improvement else "NO_MATERIAL_IMPROVEMENT"
    state = _optimization_state(client, config, asset_scope, exclude_run_id=run_id)
    converged = (
        current_generation >= MAX_GENERATIONS
        or (not material_improvement and state["consecutive_non_improving"] >= 1)
    )
    convergence_reason = None
    if current_generation >= MAX_GENERATIONS:
        convergence_reason = f"Se alcanzo el maximo de {MAX_GENERATIONS} generaciones."
    elif converged:
        convergence_reason = "Dos generaciones consecutivas no lograron una mejora material ajustada por riesgo."
    promotion = (
        "REQUIERE_VALIDACION_PAPER_Y_APROBACION_EXPLICITA"
        if converged and material_improvement else "MANTENER_SOLO_BACKTEST"
    )
    prompt = (
        "Eres auditor de backtesting. Responde en espanol y solo interpreta los datos. "
        "No autorices cambios productivos ni prometas retornos. Cada V1-V4 tiene una cartera independiente de CLP 10.000.000; no las sumes. "
        "Prioriza capital final neto de costos, drawdown maximo, profit factor, cola de perdidas y muestra. "
        "El experimento es solo para el grupo " + asset_scope + " (" + ", ".join(scope["tickers"]) + ") y la estrategia " + target_strategy_version + ". "
        "Devuelve JSON con conclusion, risks, proposed_candidate_ids y evidence.\n"
        + json.dumps({"strategy_rows": rows, "candidate_scores": candidates, "previous_best": previous_best}, default=str, ensure_ascii=True)
    )
    ai_text = None
    ai_review_called = bool(payload.get("ai_review", True)) and bool(config.get("ai_review_enabled", True)) and bool(config.get("openai_api_key"))
    if ai_review_called:
        from openai import OpenAI
        ai_text = OpenAI(api_key=config["openai_api_key"], timeout=90).responses.create(model=config["openai_model"], input=prompt).output_text
    selected = [{"candidate_id": row["candidate_id"], "promotion": promotion} for row in eligible]
    errors = client.insert_rows_json(config["audits_table"], [{
        "run_id": run_id, "created_at": datetime.utcnow().isoformat(),
        "audit_status": "PROPOSED_FOR_BACKTEST_REVIEW" if eligible else "NO_ELIGIBLE_CANDIDATE",
        "selected_candidates_json": json.dumps(selected), "evidence_json": json.dumps({"strategy_rows": rows, "candidate_scores": candidates, "previous_best": previous_best}, default=str),
        "ai_interpretation": ai_text, "model_name": config.get("openai_model"), "production_change_allowed": False,
        "generation": current_generation, "generation_outcome": outcome,
        "material_improvement": material_improvement, "best_validation_score": best["risk_adjusted_score"],
        "convergence_reason": convergence_reason, "promotion_recommendation": promotion,
        "asset_scope": asset_scope, "target_strategy_version": target_strategy_version,
    }])
    if errors:
        raise RuntimeError(f"Could not save audit: {errors}")
    return {
        "run_id": run_id, "generation": current_generation, "status": "REVIEW_SAVED",
        "asset_scope": asset_scope, "tickers": scope["tickers"], "strategy_version": target_strategy_version,
        "eligible_count": len(eligible), "material_improvement": material_improvement,
        "converged": converged, "promotion_recommendation": promotion,
        "production_change_allowed": False, "ai_review_called": ai_review_called,
        "best_candidate": best, "results": rows,
    }


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

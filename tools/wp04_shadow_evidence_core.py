"""Capture read-only, fail-closed evidence for the WP-04 BigQuery shadow."""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import subprocess
import sys
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.common.data_contracts import compare_schema, load_contract


PROJECT = re.compile(r"^[A-Za-z][A-Za-z0-9-]{4,62}$")
DATASET = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,1023}$")
MUTATING = re.compile(
    r"\b(?:INSERT|UPDATE|DELETE|MERGE|CREATE|ALTER|DROP|TRUNCATE|CALL|EXPORT|LOAD|GRANT|REVOKE)\b",
    re.I,
)
CONTRACT_TABLES = (
    "market_price_raw",
    "corporate_actions_pit",
    "market_session_calendar",
    "price_source_reconciliation",
    "market_price_canonical",
    "fx_rates_pit",
)
REQUIRED_TABLES = CONTRACT_TABLES + (
    "trading_price_features_canonical_shadow",
    "trading_price_features_wp04_shadow",
    "wp04_legacy_vs_canonical_shadow",
    "audit_canonical_prices",
)


class Wp04EvidenceError(ValueError):
    """WP-04 evidence scope or returned data fails a hard contract."""


def _default(value: Any):
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    raise TypeError(type(value).__name__)


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=_default,
    )


def digest(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def validate_scope(project_id: str, dataset_id: str, location: str):
    project_id = str(project_id or "").strip()
    dataset_id = str(dataset_id or "").strip()
    location = str(location or "").strip()
    if not PROJECT.fullmatch(project_id):
        raise Wp04EvidenceError("project_id is invalid")
    if not DATASET.fullmatch(dataset_id) or "shadow" not in dataset_id.lower():
        raise Wp04EvidenceError("dataset_id must be a valid shadow dataset")
    if not re.fullmatch(r"[A-Za-z0-9-]+", location):
        raise Wp04EvidenceError("location is invalid")
    return project_id, dataset_id, location


def fqtn(project: str, dataset: str, table: str) -> str:
    if table not in REQUIRED_TABLES:
        raise Wp04EvidenceError(f"unregistered evidence table {table}")
    return f"`{project}.{dataset}.{table}`"


def read_only(sql: str) -> str:
    sql = str(sql or "").strip()
    if not sql.upper().startswith(("SELECT", "WITH")):
        raise Wp04EvidenceError("evidence SQL must begin with SELECT or WITH")
    if MUTATING.search(sql):
        raise Wp04EvidenceError("mutating SQL is forbidden in evidence capture")
    return sql


def build_queries(project: str, dataset: str) -> dict[str, str]:
    project, dataset, _ = validate_scope(project, dataset, "us-east1")
    raw = fqtn(project, dataset, "market_price_raw")
    actions = fqtn(project, dataset, "corporate_actions_pit")
    calendar = fqtn(project, dataset, "market_session_calendar")
    reconciliation = fqtn(project, dataset, "price_source_reconciliation")
    canonical = fqtn(project, dataset, "market_price_canonical")
    fx = fqtn(project, dataset, "fx_rates_pit")
    features = fqtn(project, dataset, "trading_price_features_canonical_shadow")
    bridge = fqtn(project, dataset, "trading_price_features_wp04_shadow")
    comparison = fqtn(project, dataset, "wp04_legacy_vs_canonical_shadow")
    audit = fqtn(project, dataset, "audit_canonical_prices")
    queries = {
        "raw_summary": f"""
          SELECT
            COUNT(*) AS row_count,
            COUNT(DISTINCT raw_revision_id) AS distinct_revision_count,
            COUNT(*) - COUNT(DISTINCT raw_revision_id) AS duplicate_revision_count,
            COUNTIF(available_at < bar_end) AS available_before_bar_end_count,
            COUNTIF(open <= 0 OR high <= 0 OR low <= 0 OR close <= 0 OR high < GREATEST(open, low, close) OR low > LEAST(open, high, close) OR volume < 0) AS invalid_ohlc_count,
            COUNTIF(provider = 'YAHOO') AS yahoo_row_count,
            COUNTIF(provider = 'STOOQ') AS stooq_row_count,
            COUNTIF(source_interval = '1d') AS daily_row_count,
            COUNTIF(source_interval = '15m') AS intraday_row_count,
            COUNTIF(source_interval = '1h') AS hourly_row_count,
            COUNTIF(asset_type IN ('STOCK','ETF')) AS equity_row_count,
            COUNTIF(asset_type = 'CRYPTO') AS crypto_row_count,
            COUNTIF(asset_type = 'FX') AS fx_row_count,
            ARRAY_AGG(DISTINCT provider ORDER BY provider) AS providers,
            ARRAY_AGG(DISTINCT source_interval ORDER BY source_interval) AS source_intervals,
            MIN(bar_start) AS min_bar_start,
            MAX(bar_end) AS max_bar_end,
            MAX(ingested_at) AS max_ingested_at
          FROM {raw}
        """,
        "action_summary": f"""
          SELECT
            COUNT(*) AS row_count,
            COUNT(DISTINCT action_id) AS distinct_action_count,
            COUNT(*) - COUNT(DISTINCT action_id) AS duplicate_action_count,
            COUNTIF(action_type = 'SPLIT') AS split_count,
            COUNTIF(action_type = 'DIVIDEND') AS dividend_count,
            COUNTIF(backtest_eligible) AS eligible_action_count,
            COUNTIF(backtest_eligible AND source_published_at IS NULL) AS invalid_eligible_availability_count,
            COUNTIF(NOT backtest_eligible AND quality_status = 'UNVERIFIED_AVAILABLE_AT') AS fail_closed_action_count
          FROM {actions}
        """,
        "calendar_summary": f"""
          SELECT
            COUNT(*) AS row_count,
            COUNT(DISTINCT session_id) AS distinct_session_count,
            COUNT(*) - COUNT(DISTINCT session_id) AS duplicate_session_id_count,
            (SELECT COUNT(*) FROM (SELECT exchange, asset_type, session_date FROM {calendar} GROUP BY exchange, asset_type, session_date HAVING COUNT(*) > 1)) AS duplicate_session_key_count,
            COUNTIF(close_utc <= open_utc) AS invalid_duration_count,
            COUNTIF(exchange = 'XNYS') AS xnys_count,
            COUNTIF(exchange = 'CRYPTO_24_7') AS crypto_calendar_count,
            COUNTIF(exchange = 'FX_24_5') AS fx_calendar_count,
            COUNTIF(exchange = 'XNYS' AND session_status = 'EARLY_CLOSE') AS early_close_count,
            COUNT(DISTINCT calendar_hash) AS calendar_hash_count
          FROM {calendar}
        """,
        "reconciliation_summary": f"""
          SELECT
            COUNT(*) AS row_count,
            COUNT(DISTINCT reconciliation_id) AS distinct_reconciliation_count,
            COUNT(*) - COUNT(DISTINCT reconciliation_id) AS duplicate_reconciliation_count,
            COUNTIF(status = 'MATCH') AS match_count,
            COUNTIF(status = 'WITHIN_TOLERANCE') AS within_tolerance_count,
            COUNTIF(status = 'MATERIAL_MISMATCH') AS material_mismatch_count,
            COUNTIF(status = 'SOURCE_MISSING') AS source_missing_count,
            COUNTIF(status = 'STALE_SOURCE') AS stale_source_count,
            COUNTIF(status IN ('MATERIAL_MISMATCH','STALE_SOURCE') AND NOT blocks_quality) AS unblocked_material_problem_count,
            COUNTIF(production_change_allowed) AS production_change_violation_count
          FROM {reconciliation}
        """,
        "canonical_summary": f"""
          SELECT
            COUNT(*) AS row_count,
            COUNT(DISTINCT price_id) AS distinct_price_count,
            COUNT(*) - COUNT(DISTINCT price_id) AS duplicate_price_id_count,
            (SELECT COUNT(*) FROM (SELECT ticker, bar_start, canonical_interval FROM {canonical} GROUP BY ticker, bar_start, canonical_interval HAVING COUNT(*) > 1)) AS duplicate_canonical_key_count,
            COUNTIF(available_at < bar_end) AS available_before_bar_end_count,
            COUNTIF(raw_open <= 0 OR raw_high <= 0 OR raw_low <= 0 OR raw_close <= 0 OR adjusted_close <= 0 OR raw_high < GREATEST(raw_open, raw_low, raw_close) OR raw_low > LEAST(raw_open, raw_high, raw_close) OR raw_volume < 0) AS invalid_ohlc_count,
            COUNTIF((selected_by_rule = 'INTRADAY_COMPLETE' AND source_interval != '15m') OR (STARTS_WITH(selected_by_rule, 'DAILY_FALLBACK') AND source_interval != '1d')) AS mixed_selection_count,
            COUNTIF(selected_by_rule = 'CRYPTO_4H_COMPLETE' AND (canonical_interval != '4h' OR source_interval != '1h' OR ARRAY_LENGTH(source_revision_ids) != 4)) AS invalid_crypto_bucket_count,
            COUNTIF(quality_status IN ('MATERIAL_MISMATCH','STALE_SOURCE','SOURCE_MISSING')) AS blocked_quality_count,
            COUNTIF(quality_status IN ('CANONICAL_RECONCILED','CANONICAL_COVERAGE_ACCEPTED','CANONICAL_DAILY_FALLBACK','CANONICAL_SINGLE_SOURCE')) AS eligible_quality_count,
            COUNTIF(selected_by_rule = 'INTRADAY_COMPLETE') AS intraday_selected_count,
            COUNTIF(STARTS_WITH(selected_by_rule, 'DAILY_FALLBACK')) AS daily_fallback_count,
            COUNTIF(selected_by_rule = 'CRYPTO_4H_COMPLETE') AS crypto_4h_count,
            COUNTIF(split_factor != 1) AS split_applied_count,
            COUNTIF(dividend_amount != 0) AS dividend_applied_count,
            COUNTIF(production_change_allowed) AS production_change_violation_count
          FROM {canonical}
        """,
        "feature_summary": f"""
          SELECT
            COUNT(*) AS row_count,
            (SELECT COUNT(*) FROM (SELECT analysis_date, ticker, signal_hour FROM {features} GROUP BY analysis_date, ticker, signal_hour HAVING COUNT(*) > 1)) AS duplicate_feature_key_count,
            COUNTIF(price_available_at > signal_timestamp) AS price_after_signal_count,
            COUNTIF(production_change_allowed) AS production_change_violation_count,
            COUNTIF(asset_type IN ('STOCK','ETF')) AS equity_feature_count,
            COUNTIF(asset_type = 'CRYPTO') AS crypto_feature_count,
            (SELECT COUNT(*) FROM {features} f JOIN {canonical} p ON p.price_id = f.price_id WHERE p.quality_status IN ('MATERIAL_MISMATCH','STALE_SOURCE','SOURCE_MISSING')) AS blocked_price_consumption_count
          FROM {features}
        """,
        "fx_summary": f"""
          SELECT
            COUNT(*) AS row_count,
            COUNT(*) - COUNT(DISTINCT fx_rate_id) AS duplicate_rate_id_count,
            (SELECT COUNT(*) FROM (SELECT rate_date, base_currency, quote_currency FROM {fx} GROUP BY rate_date, base_currency, quote_currency HAVING COUNT(*) > 1)) AS duplicate_rate_key_count,
            COUNTIF(rate <= 0 OR base_currency != 'USD' OR quote_currency != 'CLP') AS invalid_rate_count,
            COUNTIF(production_change_allowed) AS production_change_violation_count
          FROM {fx}
        """,
        "bridge_summary": f"""
          SELECT
            COUNT(*) AS row_count,
            COUNTIF(selected_feature_source = 'CANONICAL_WP04') AS canonical_source_count,
            COUNTIF(selected_feature_source = 'LEGACY_ROLLBACK') AS legacy_source_count,
            COUNTIF(promotion_eligible) AS promotion_violation_count,
            COUNTIF(production_change_allowed) AS production_change_violation_count
          FROM {bridge}
        """,
        "comparison_summary": f"""
          SELECT
            COUNT(*) AS row_count,
            COUNTIF(promotion_eligible) AS promotion_violation_count,
            COUNTIF(production_change_allowed) AS production_change_violation_count,
            ARRAY_AGG(STRUCT(comparison_status, row_count) ORDER BY comparison_status) AS status_counts
          FROM (
            SELECT comparison_status, promotion_eligible, production_change_allowed, COUNT(*) AS row_count
            FROM {comparison}
            GROUP BY comparison_status, promotion_eligible, production_change_allowed
          )
        """,
        "audit_summary": f"""
          SELECT
            COUNT(*) AS violation_count,
            ARRAY_AGG(STRUCT(violation, ticker, evaluated_at, available_at, record_id) ORDER BY violation, ticker LIMIT 100) AS sample_violations
          FROM {audit}
        """,
    }
    return {name: read_only(sql) for name, sql in queries.items()}


def _plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if hasattr(value, "items"):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (dt.datetime, dt.date, dt.time, Decimal, bytes)):
        return _default(value)
    return value


def _one(job) -> dict[str, Any]:
    rows = list(job.result(timeout=300))
    if len(rows) != 1:
        raise Wp04EvidenceError(
            f"evidence query returned {len(rows)} rows; expected one"
        )
    return _plain(dict(rows[0].items()))


def _count(row: Mapping[str, Any], key: str) -> int:
    return int(row.get(key) or 0)


def evaluate(
    *,
    results: Mapping[str, Mapping[str, Any]],
    schema_drift: Mapping[str, list[str]],
) -> dict[str, Any]:
    required = {
        "raw_summary",
        "action_summary",
        "calendar_summary",
        "reconciliation_summary",
        "canonical_summary",
        "feature_summary",
        "fx_summary",
        "bridge_summary",
        "comparison_summary",
        "audit_summary",
    }
    missing = sorted(required - set(results))
    if missing:
        raise Wp04EvidenceError(f"missing evidence query results: {missing}")
    problems = []
    warnings = []
    for table, drift in sorted(schema_drift.items()):
        if drift:
            problems.append(
                {"code": "SCHEMA_DRIFT", "table": table, "details": drift}
            )

    raw = results["raw_summary"]
    if _count(raw, "row_count") <= 0:
        problems.append({"code": "RAW_PRICE_EMPTY"})
    for key, code in (
        ("duplicate_revision_count", "RAW_DUPLICATE_REVISION"),
        ("available_before_bar_end_count", "RAW_AVAILABLE_BEFORE_BAR_END"),
        ("invalid_ohlc_count", "RAW_INVALID_OHLC"),
    ):
        if _count(raw, key):
            problems.append({"code": code, "count": _count(raw, key)})
    for key, code in (
        ("yahoo_row_count", "YAHOO_ROWS_MISSING"),
        ("stooq_row_count", "STOOQ_ROWS_MISSING"),
        ("daily_row_count", "DAILY_ROWS_MISSING"),
        ("intraday_row_count", "INTRADAY_ROWS_MISSING"),
        ("hourly_row_count", "HOURLY_ROWS_MISSING"),
        ("equity_row_count", "EQUITY_ROWS_MISSING"),
        ("crypto_row_count", "CRYPTO_ROWS_MISSING"),
        ("fx_row_count", "FX_ROWS_MISSING"),
    ):
        if _count(raw, key) <= 0:
            problems.append({"code": code})

    actions = results["action_summary"]
    if _count(actions, "row_count") <= 0:
        warnings.append({"code": "NO_CORPORATE_ACTION_ROWS_IN_BOUNDED_SAMPLE"})
    if _count(actions, "duplicate_action_count"):
        problems.append(
            {
                "code": "DUPLICATE_CORPORATE_ACTION",
                "count": _count(actions, "duplicate_action_count"),
            }
        )
    if _count(actions, "invalid_eligible_availability_count"):
        problems.append(
            {
                "code": "ACTION_ELIGIBLE_WITHOUT_PUBLICATION",
                "count": _count(actions, "invalid_eligible_availability_count"),
            }
        )
    if _count(actions, "eligible_action_count") <= 0:
        warnings.append(
            {"code": "NO_VERIFIED_PIT_ACTIONS_HISTORICAL_PROVIDER_LIMITATION"}
        )

    calendar = results["calendar_summary"]
    if _count(calendar, "row_count") <= 0:
        problems.append({"code": "SESSION_CALENDAR_EMPTY"})
    for key, code in (
        ("duplicate_session_id_count", "DUPLICATE_SESSION_ID"),
        ("duplicate_session_key_count", "DUPLICATE_SESSION_KEY"),
        ("invalid_duration_count", "INVALID_SESSION_DURATION"),
    ):
        if _count(calendar, key):
            problems.append({"code": code, "count": _count(calendar, key)})
    for key, code in (
        ("xnys_count", "XNYS_CALENDAR_MISSING"),
        ("crypto_calendar_count", "CRYPTO_CALENDAR_MISSING"),
        ("fx_calendar_count", "FX_CALENDAR_MISSING"),
    ):
        if _count(calendar, key) <= 0:
            problems.append({"code": code})

    reconciliation = results["reconciliation_summary"]
    if _count(reconciliation, "row_count") <= 0:
        problems.append({"code": "RECONCILIATION_EMPTY"})
    for key, code in (
        ("duplicate_reconciliation_count", "DUPLICATE_RECONCILIATION"),
        ("unblocked_material_problem_count", "UNBLOCKED_RECONCILIATION_PROBLEM"),
        ("production_change_violation_count", "RECONCILIATION_PRODUCTION_CHANGE"),
    ):
        if _count(reconciliation, key):
            problems.append({"code": code, "count": _count(reconciliation, key)})
    for key, code in (
        ("material_mismatch_count", "MATERIAL_MISMATCHES_BLOCKED"),
        ("source_missing_count", "SECONDARY_SOURCE_MISSING"),
        ("stale_source_count", "STALE_SOURCE_ROWS_BLOCKED"),
    ):
        if _count(reconciliation, key):
            warnings.append({"code": code, "count": _count(reconciliation, key)})

    canonical = results["canonical_summary"]
    if _count(canonical, "row_count") <= 0:
        problems.append({"code": "CANONICAL_PRICE_EMPTY"})
    if _count(canonical, "eligible_quality_count") <= 0:
        problems.append({"code": "NO_ELIGIBLE_CANONICAL_PRICES"})
    for key, code in (
        ("duplicate_price_id_count", "DUPLICATE_PRICE_ID"),
        ("duplicate_canonical_key_count", "DUPLICATE_CANONICAL_KEY"),
        ("available_before_bar_end_count", "CANONICAL_AVAILABLE_BEFORE_BAR_END"),
        ("invalid_ohlc_count", "CANONICAL_INVALID_OHLC"),
        ("mixed_selection_count", "MIXED_DAILY_INTRADAY_SELECTION"),
        ("invalid_crypto_bucket_count", "INVALID_CRYPTO_4H_BUCKET"),
        ("production_change_violation_count", "CANONICAL_PRODUCTION_CHANGE"),
    ):
        if _count(canonical, key):
            problems.append({"code": code, "count": _count(canonical, key)})
    if _count(canonical, "intraday_selected_count") <= 0:
        warnings.append({"code": "NO_COMPLETE_INTRADAY_SESSION_SELECTED"})

    features = results["feature_summary"]
    if _count(features, "row_count") <= 0:
        problems.append({"code": "CANONICAL_FEATURES_EMPTY"})
    for key, code in (
        ("duplicate_feature_key_count", "DUPLICATE_FEATURE_KEY"),
        ("price_after_signal_count", "PRICE_AVAILABLE_AFTER_SIGNAL"),
        ("production_change_violation_count", "FEATURE_PRODUCTION_CHANGE"),
        ("blocked_price_consumption_count", "BLOCKED_PRICE_CONSUMED"),
    ):
        if _count(features, key):
            problems.append({"code": code, "count": _count(features, key)})

    fx = results["fx_summary"]
    if _count(fx, "row_count") <= 0:
        problems.append({"code": "FX_RATES_EMPTY"})
    for key, code in (
        ("duplicate_rate_id_count", "DUPLICATE_FX_RATE_ID"),
        ("duplicate_rate_key_count", "DUPLICATE_FX_RATE_KEY"),
        ("invalid_rate_count", "INVALID_USD_CLP_RATE"),
        ("production_change_violation_count", "FX_PRODUCTION_CHANGE"),
    ):
        if _count(fx, key):
            problems.append({"code": code, "count": _count(fx, key)})

    bridge = results["bridge_summary"]
    if _count(bridge, "row_count") <= 0 or _count(bridge, "canonical_source_count") <= 0:
        problems.append({"code": "CANONICAL_FEATURE_BRIDGE_EMPTY"})
    for key, code in (
        ("legacy_source_count", "BRIDGE_USED_LEGACY_SOURCE"),
        ("promotion_violation_count", "BRIDGE_PROMOTION_ELIGIBLE"),
        ("production_change_violation_count", "BRIDGE_PRODUCTION_CHANGE"),
    ):
        if _count(bridge, key):
            problems.append({"code": code, "count": _count(bridge, key)})

    comparison = results["comparison_summary"]
    if _count(comparison, "row_count") <= 0:
        problems.append({"code": "LEGACY_CANONICAL_COMPARISON_EMPTY"})
    for key, code in (
        ("promotion_violation_count", "COMPARISON_PROMOTION_ELIGIBLE"),
        ("production_change_violation_count", "COMPARISON_PRODUCTION_CHANGE"),
    ):
        if _count(comparison, key):
            problems.append({"code": code, "count": _count(comparison, key)})

    audit = results["audit_summary"]
    if _count(audit, "violation_count"):
        problems.append(
            {
                "code": "AUDIT_CANONICAL_PRICE_VIOLATION",
                "count": _count(audit, "violation_count"),
            }
        )
    return {
        "status": "PASS" if not problems else "FAIL",
        "hard_gate_count": len(problems),
        "warning_count": len(warnings),
        "problems": problems,
        "warnings": warnings,
    }


def _schema(table) -> list[dict[str, str]]:
    return [
        {"name": field.name, "type": field.field_type, "mode": field.mode}
        for field in table.schema
    ]


def capture(
    *,
    project_id: str,
    dataset_id: str,
    location: str,
    git_sha: str,
    ci_run_id: str,
) -> dict[str, Any]:
    project_id, dataset_id, location = validate_scope(
        project_id,
        dataset_id,
        location,
    )
    if not re.fullmatch(r"[0-9a-f]{40}", git_sha):
        raise Wp04EvidenceError("git_sha must be a full lowercase SHA")
    if not re.fullmatch(r"\d+", str(ci_run_id)):
        raise Wp04EvidenceError("ci_run_id must be numeric")
    try:
        from google.cloud import bigquery
    except ImportError as exc:
        raise Wp04EvidenceError(
            "google-cloud-bigquery is required for evidence capture"
        ) from exc
    client = bigquery.Client(project=project_id, location=location)
    dataset = client.get_dataset(f"{project_id}.{dataset_id}")
    labels = dict(dataset.labels or {})
    if str(dataset.location).lower() != location.lower():
        raise Wp04EvidenceError("dataset location mismatch")
    if (
        labels.get("environment") != "shadow"
        or labels.get("work_package") != "wp04"
    ):
        raise Wp04EvidenceError(
            "dataset must be labeled environment=shadow and work_package=wp04"
        )

    metadata = {}
    missing = []
    tables = {}
    for name in REQUIRED_TABLES:
        try:
            table = client.get_table(f"{project_id}.{dataset_id}.{name}")
        except Exception:
            missing.append(name)
            continue
        tables[name] = table
        metadata[name] = {
            "table_id": table.full_table_id,
            "table_type": getattr(table, "table_type", None),
            "num_rows": getattr(table, "num_rows", None),
            "modified": getattr(table, "modified", None),
            "schema_sha256": digest(_schema(table)),
        }
    if missing:
        raise Wp04EvidenceError(f"missing required WP-04 tables: {missing}")

    schema_drift = {}
    for name in CONTRACT_TABLES:
        contract = load_contract(ROOT / "contracts" / f"{name}.yaml")
        schema_drift[name] = compare_schema(
            contract,
            _schema(tables[name]),
            allow_extra_columns=False,
        )

    query_results = {}
    query_hashes = {}
    job_ids = {}
    for name, sql in build_queries(project_id, dataset_id).items():
        query_hashes[name] = hashlib.sha256(sql.encode("utf-8")).hexdigest()
        job = client.query(
            sql,
            job_config=bigquery.QueryJobConfig(use_legacy_sql=False),
            location=location,
        )
        query_results[name] = _one(job)
        job_ids[name] = job.job_id
    evaluation = evaluate(results=query_results, schema_drift=schema_drift)
    manifest = json.loads(
        (ROOT / "contracts" / "manifest.json").read_text(encoding="utf-8")
    )
    stable = {
        "schema_version": 1,
        "operation": "WP04_SHADOW_EVIDENCE_CAPTURE",
        "project_id": project_id,
        "dataset_id": dataset_id,
        "dataset_labels": labels,
        "location": location,
        "git_sha": git_sha,
        "ci_run_id": str(ci_run_id),
        "contract_set_hash": manifest["contract_set_hash"],
        "schema_snapshot_hash": manifest["schema_snapshot_hash"],
        "schema_drift": schema_drift,
        "table_metadata": metadata,
        "query_hashes": query_hashes,
        "query_job_ids": job_ids,
        "query_results": query_results,
        "evaluation": evaluation,
        "production_change_allowed": False,
    }
    return {
        **stable,
        "evidence_checksum": digest(stable),
        "captured_at": dt.datetime.now(dt.timezone.utc).isoformat(),
    }


def current_sha() -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def write_output(document: Mapping[str, Any], output: Path | None) -> None:
    text = json.dumps(document, indent=2, sort_keys=True, default=_default) + "\n"
    if output is None:
        print(text, end="")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
        print(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--location", default="us-east1")
    parser.add_argument("--environment", default="shadow")
    parser.add_argument("--git-sha")
    parser.add_argument("--ci-run-id", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.environment != "shadow":
            raise Wp04EvidenceError(
                "WP-04 evidence capture is restricted to shadow"
            )
        result = capture(
            project_id=args.project_id,
            dataset_id=args.dataset_id,
            location=args.location,
            git_sha=args.git_sha or current_sha(),
            ci_run_id=args.ci_run_id,
        )
        write_output(result, args.output)
        return 0 if result["evaluation"]["status"] == "PASS" else 2
    except (
        OSError,
        subprocess.SubprocessError,
        ValueError,
        Wp04EvidenceError,
    ) as exc:
        print(
            json.dumps(
                {
                    "status": "FAIL",
                    "error": str(exc),
                    "production_change_allowed": False,
                },
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

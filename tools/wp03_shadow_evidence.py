"""Capture fail-closed, read-only evidence for the WP-03 shadow validation.

The tool executes only fixed ``SELECT``/``WITH`` queries against the explicitly
selected BigQuery project and dataset. It never creates tables, starts Dataform,
changes Cloud Run, modifies schedulers, or invokes broker APIs.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from datetime import date, datetime, time, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from packages.common.data_contracts import compare_schema, load_contract


IDENTIFIER = re.compile(r"^[A-Za-z0-9_]+$")
PROJECT_ID = re.compile(r"^[A-Za-z][A-Za-z0-9-]{4,62}$")
MUTATING_SQL = re.compile(
    r"\b(?:INSERT|UPDATE|DELETE|MERGE|CREATE|ALTER|DROP|TRUNCATE|CALL|EXPORT|LOAD|GRANT|REVOKE)\b",
    re.IGNORECASE,
)
REQUIRED_TABLES = (
    "financial_statements_pit_raw",
    "financial_statements_pit",
    "financial_quarters_pit",
    "financial_ttm_pit",
    "earnings_events_pit",
    "trading_earnings_context_pit",
    "portfolio_valuation_pit_shadow",
    "audit_no_lookahead",
    "wp03_legacy_vs_pit_shadow",
    "wp03_legacy_invalidation",
)


class EvidenceError(ValueError):
    """The requested evidence scope or returned data is invalid."""


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=_json_default,
    )


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _json_default(value: Any):
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return value.hex()
    raise TypeError(f"Unsupported JSON evidence value: {type(value).__name__}")


def validate_scope(project_id: str, dataset_id: str, location: str) -> tuple[str, str, str]:
    project_id = str(project_id or "").strip()
    dataset_id = str(dataset_id or "").strip()
    location = str(location or "").strip()
    if not PROJECT_ID.fullmatch(project_id):
        raise EvidenceError("project_id is not a valid Google Cloud project identifier")
    if not IDENTIFIER.fullmatch(dataset_id):
        raise EvidenceError("dataset_id is not a valid BigQuery dataset identifier")
    if not re.fullmatch(r"^[A-Za-z0-9-]+$", location):
        raise EvidenceError("location is invalid")
    return project_id, dataset_id, location


def fqtn(project_id: str, dataset_id: str, table_name: str) -> str:
    if not IDENTIFIER.fullmatch(table_name):
        raise EvidenceError(f"invalid table name: {table_name}")
    return f"`{project_id}.{dataset_id}.{table_name}`"


def assert_read_only_sql(sql: str) -> str:
    normalized = str(sql or "").strip()
    if not normalized:
        raise EvidenceError("empty evidence query")
    if not normalized.upper().startswith(("SELECT", "WITH")):
        raise EvidenceError("evidence query must begin with SELECT or WITH")
    if MUTATING_SQL.search(normalized):
        raise EvidenceError("mutating SQL is forbidden in WP-03 evidence capture")
    return normalized


def build_queries(project_id: str, dataset_id: str, mapping_version: str) -> dict[str, str]:
    project_id, dataset_id, _ = validate_scope(project_id, dataset_id, "us-east1")
    mapping_version = str(mapping_version or "").strip()
    if not mapping_version or not re.fullmatch(r"^[A-Za-z0-9._-]+$", mapping_version):
        raise EvidenceError("mapping_version is invalid")

    raw = fqtn(project_id, dataset_id, "financial_statements_pit_raw")
    canonical = fqtn(project_id, dataset_id, "financial_statements_pit")
    quarters = fqtn(project_id, dataset_id, "financial_quarters_pit")
    ttm = fqtn(project_id, dataset_id, "financial_ttm_pit")
    events = fqtn(project_id, dataset_id, "earnings_events_pit")
    earnings_context = fqtn(project_id, dataset_id, "trading_earnings_context_pit")
    valuation = fqtn(project_id, dataset_id, "portfolio_valuation_pit_shadow")
    no_lookahead = fqtn(project_id, dataset_id, "audit_no_lookahead")
    comparison = fqtn(project_id, dataset_id, "wp03_legacy_vs_pit_shadow")
    invalidation = fqtn(project_id, dataset_id, "wp03_legacy_invalidation")

    queries = {
        "raw_summary": f"""
            SELECT
              COUNT(*) AS row_count,
              COUNT(DISTINCT revision_id) AS distinct_revision_count,
              COUNT(*) - COUNT(DISTINCT revision_id) AS duplicate_revision_count,
              COUNTIF(backtest_eligible) AS eligible_row_count,
              COUNTIF(NOT backtest_eligible) AS rejected_row_count,
              COUNTIF(mapping_version != '{mapping_version}') AS unexpected_mapping_count,
              ARRAY_AGG(DISTINCT mapping_version ORDER BY mapping_version) AS mapping_versions,
              MIN(available_at) AS min_available_at,
              MAX(available_at) AS max_available_at,
              MIN(loaded_at) AS min_loaded_at,
              MAX(loaded_at) AS max_loaded_at
            FROM {raw}
        """,
        "canonical_summary": f"""
            SELECT
              COUNT(*) AS row_count,
              COUNT(DISTINCT revision_id) AS distinct_revision_count,
              COUNTIF(mapping_version != '{mapping_version}') AS unexpected_mapping_count,
              COUNTIF(revision_number <= 0) AS invalid_revision_number_count,
              COUNTIF(is_restated) AS restated_row_count,
              COUNTIF(available_at IS NULL OR source_published_at IS NULL) AS missing_availability_count,
              COUNTIF(available_at != source_published_at) AS availability_mismatch_count,
              COUNTIF(quality_status != 'ELIGIBLE_VERIFIED_PIT') AS invalid_quality_count,
              MAX(revision_number) AS max_revision_number
            FROM {canonical}
        """,
        "quarter_summary": f"""
            SELECT
              COUNT(*) AS row_count,
              COUNTIF(fiscal_quarter = 4) AS q4_row_count,
              COUNTIF(fiscal_quarter = 4 AND NOT quarter_structure_complete) AS incomplete_q4_count,
              COUNTIF(available_at > signal_timestamp) AS available_after_signal_count,
              COUNTIF(
                derivation_component_max_available_at IS NOT NULL
                AND derivation_component_max_available_at > available_at
              ) AS q4_component_after_annual_count,
              COUNTIF(
                derivation_component_max_available_at IS NOT NULL
                AND derivation_component_max_available_at > signal_timestamp
              ) AS q4_component_after_signal_count,
              COUNTIF(currency IS NULL) AS missing_currency_count
            FROM {quarters}
        """,
        "ttm_summary": f"""
            SELECT
              COUNT(*) AS row_count,
              COUNTIF(ttm_complete) AS complete_row_count,
              COUNTIF(
                ttm_complete AND (
                  quarter_count != 4
                  OR distinct_quarter_count != 4
                  OR quarter_ordinal_span != 3
                  OR currency_count != 1
                  OR normalized_quarter_count != 4
                  OR revenue_quarter_count != 4
                  OR net_income_quarter_count != 4
                )
              ) AS invalid_complete_row_count,
              COUNTIF(latest_financial_available_at > signal_timestamp) AS available_after_signal_count,
              COUNTIF(ttm_derivation_lineage_json IS NULL) AS missing_lineage_count
            FROM {ttm}
        """,
        "earnings_summary": f"""
            SELECT
              COUNT(*) AS row_count,
              COUNTIF(event_kind = 'EXPECTED') AS expected_row_count,
              COUNTIF(event_kind = 'REPORTED') AS reported_row_count,
              COUNTIF(event_kind NOT IN ('EXPECTED', 'REPORTED')) AS invalid_kind_count,
              COUNTIF(available_at != observed_at OR ingested_at != observed_at) AS availability_mismatch_count,
              COUNTIF(revision <= 0) AS invalid_revision_count,
              COUNTIF(NOT backtest_eligible) AS ineligible_row_count,
              COUNT(*) - COUNT(DISTINCT event_id) AS duplicate_event_count
            FROM {events}
        """,
        "earnings_context_summary": f"""
            SELECT
              COUNT(*) AS row_count,
              COUNTIF(expected_available_at > signal_timestamp_utc) AS expected_after_signal_count,
              COUNTIF(reported_available_at > signal_timestamp_utc) AS reported_after_signal_count,
              COUNTIF(
                earnings_event_status LIKE 'RECENT_%'
                AND (reported_age_days IS NULL OR reported_age_days NOT BETWEEN 0 AND 5)
              ) AS stale_recent_status_count
            FROM {earnings_context}
        """,
        "valuation_summary": f"""
            SELECT
              COUNT(*) AS row_count,
              COUNTIF(promotion_mode != 'SHADOW_ONLY') AS promotion_mode_violation_count,
              COUNTIF(production_change_allowed) AS production_change_violation_count,
              COUNTIF(valuation_price_available_at > signal_timestamp_utc) AS price_after_signal_count,
              COUNTIF(latest_financial_available_at > signal_timestamp_utc) AS financial_after_signal_count,
              COUNTIF(pe_ttm_pit < 0 OR price_to_sales_ttm_pit < 0 OR price_to_book_pit < 0) AS negative_multiple_count,
              COUNTIF(reporting_currency != 'USD' AND (market_cap_pit IS NOT NULL OR pe_ttm_pit IS NOT NULL OR price_to_sales_ttm_pit IS NOT NULL OR price_to_book_pit IS NOT NULL)) AS cross_currency_arithmetic_count
            FROM {valuation}
        """,
        "no_lookahead_summary": f"""
            SELECT
              COUNT(*) AS violation_count,
              ARRAY_AGG(STRUCT(violation, ticker, evaluated_at, available_at) ORDER BY violation, ticker LIMIT 100) AS sample_violations
            FROM {no_lookahead}
        """,
        "comparison_summary": f"""
            SELECT
              COUNT(*) AS row_count,
              COUNTIF(promotion_eligible) AS promotion_violation_count,
              ARRAY_AGG(STRUCT(comparison_status, row_count) ORDER BY comparison_status) AS status_counts
            FROM (
              SELECT comparison_status, promotion_eligible, COUNT(*) AS row_count
              FROM {comparison}
              GROUP BY comparison_status, promotion_eligible
            )
        """,
        "invalidation_summary": f"""
            SELECT
              COUNT(*) AS row_count,
              COUNTIF(promotion_eligible) AS promotion_violation_count,
              COUNTIF(legacy_classification != 'WP03_PIT_INVALIDATED') AS classification_violation_count,
              COUNTIF(recomputation_status != 'REQUIRES_RECOMPUTE_ON_WP03_PIT_SNAPSHOT') AS recomputation_violation_count
            FROM {invalidation}
        """,
    }
    return {name: assert_read_only_sql(sql) for name, sql in queries.items()}


def _as_plain(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _as_plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_as_plain(item) for item in value]
    if hasattr(value, "items"):
        return {str(key): _as_plain(item) for key, item in value.items()}
    if isinstance(value, (datetime, date, time, Decimal, bytes)):
        return _json_default(value)
    return value


def _first_row(job) -> dict[str, Any]:
    rows = list(job.result(timeout=300))
    if len(rows) != 1:
        raise EvidenceError(f"evidence query returned {len(rows)} rows; expected exactly one")
    row = rows[0]
    return _as_plain(dict(row.items()))


def _table_schema_snapshot(table) -> list[dict[str, str]]:
    return [
        {"name": field.name, "type": field.field_type, "mode": field.mode}
        for field in table.schema
    ]


def capture_evidence(
    *,
    project_id: str,
    dataset_id: str,
    location: str,
    mapping_version: str,
    git_sha: str,
    ci_run_id: str,
) -> dict[str, Any]:
    project_id, dataset_id, location = validate_scope(project_id, dataset_id, location)
    if not re.fullmatch(r"^[0-9a-f]{40}$", str(git_sha or "")):
        raise EvidenceError("git_sha must be a full 40-character lowercase SHA")
    if not re.fullmatch(r"^\d+$", str(ci_run_id or "")):
        raise EvidenceError("ci_run_id must be numeric")
    try:
        from google.cloud import bigquery
    except ImportError as exc:
        raise EvidenceError("google-cloud-bigquery is required for evidence capture") from exc

    client = bigquery.Client(project=project_id, location=location)
    table_metadata: dict[str, Any] = {}
    missing_tables = []
    for table_name in REQUIRED_TABLES:
        table_id = f"{project_id}.{dataset_id}.{table_name}"
        try:
            table = client.get_table(table_id)
        except Exception:
            missing_tables.append(table_name)
            continue
        table_metadata[table_name] = {
            "table_id": table_id,
            "table_type": getattr(table, "table_type", None),
            "num_rows": getattr(table, "num_rows", None),
            "modified": getattr(table, "modified", None),
            "schema_sha256": sha256_json(_table_schema_snapshot(table)),
        }
    if missing_tables:
        raise EvidenceError(f"missing required WP-03 shadow tables: {missing_tables}")

    raw_table = client.get_table(
        f"{project_id}.{dataset_id}.financial_statements_pit_raw"
    )
    raw_contract = load_contract(
        REPO_ROOT / "contracts" / "financial_statements_pit_raw.yaml"
    )
    raw_schema_drift = compare_schema(
        raw_contract,
        _table_schema_snapshot(raw_table),
        allow_extra_columns=False,
    )

    query_results = {}
    query_hashes = {}
    query_job_ids = {}
    for name, sql in build_queries(project_id, dataset_id, mapping_version).items():
        query_hashes[name] = hashlib.sha256(sql.encode("utf-8")).hexdigest()
        job = client.query(
            sql,
            job_config=bigquery.QueryJobConfig(use_legacy_sql=False),
            location=location,
        )
        query_results[name] = _first_row(job)
        query_job_ids[name] = job.job_id

    evaluation = evaluate_results(
        query_results=query_results,
        raw_schema_drift=raw_schema_drift,
    )
    stable_payload = {
        "schema_version": 1,
        "operation": "WP03_SHADOW_EVIDENCE_CAPTURE",
        "project_id": project_id,
        "dataset_id": dataset_id,
        "location": location,
        "mapping_version": mapping_version,
        "git_sha": git_sha,
        "ci_run_id": str(ci_run_id),
        "contract_set_hash": json.loads(
            (REPO_ROOT / "contracts" / "manifest.json").read_text(encoding="utf-8")
        )["contract_set_hash"],
        "raw_schema_drift": raw_schema_drift,
        "table_metadata": table_metadata,
        "query_hashes": query_hashes,
        "query_job_ids": query_job_ids,
        "query_results": query_results,
        "evaluation": evaluation,
        "production_change_allowed": False,
    }
    evidence_checksum = sha256_json(stable_payload)
    return {
        **stable_payload,
        "evidence_checksum": evidence_checksum,
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }


def _count(result: Mapping[str, Any], key: str) -> int:
    value = result.get(key)
    return int(value or 0)


def evaluate_results(
    *,
    query_results: Mapping[str, Mapping[str, Any]],
    raw_schema_drift: list[str],
) -> dict[str, Any]:
    required = {
        "raw_summary",
        "canonical_summary",
        "quarter_summary",
        "ttm_summary",
        "earnings_summary",
        "earnings_context_summary",
        "valuation_summary",
        "no_lookahead_summary",
        "comparison_summary",
        "invalidation_summary",
    }
    missing = sorted(required - set(query_results))
    if missing:
        raise EvidenceError(f"missing query results: {missing}")

    problems = []
    warnings = []
    raw = query_results["raw_summary"]
    canonical = query_results["canonical_summary"]
    quarters = query_results["quarter_summary"]
    ttm = query_results["ttm_summary"]
    earnings = query_results["earnings_summary"]
    earnings_context = query_results["earnings_context_summary"]
    valuation = query_results["valuation_summary"]
    no_lookahead = query_results["no_lookahead_summary"]
    comparison = query_results["comparison_summary"]
    invalidation = query_results["invalidation_summary"]

    if raw_schema_drift:
        problems.append({"code": "RAW_SCHEMA_DRIFT", "details": raw_schema_drift})
    if _count(raw, "row_count") <= 0:
        problems.append({"code": "RAW_BACKFILL_EMPTY"})
    for key, code in (
        ("duplicate_revision_count", "RAW_DUPLICATE_REVISION"),
        ("unexpected_mapping_count", "RAW_UNEXPECTED_MAPPING_VERSION"),
    ):
        if _count(raw, key):
            problems.append({"code": code, "count": _count(raw, key)})
    if _count(canonical, "row_count") <= 0:
        problems.append({"code": "CANONICAL_PIT_EMPTY"})
    for key, code in (
        ("unexpected_mapping_count", "CANONICAL_UNEXPECTED_MAPPING_VERSION"),
        ("invalid_revision_number_count", "CANONICAL_INVALID_REVISION_NUMBER"),
        ("missing_availability_count", "CANONICAL_MISSING_AVAILABILITY"),
        ("availability_mismatch_count", "CANONICAL_AVAILABILITY_MISMATCH"),
        ("invalid_quality_count", "CANONICAL_INVALID_QUALITY"),
    ):
        if _count(canonical, key):
            problems.append({"code": code, "count": _count(canonical, key)})
    for key, code in (
        ("available_after_signal_count", "QUARTER_AVAILABLE_AFTER_SIGNAL"),
        ("q4_component_after_annual_count", "Q4_COMPONENT_AFTER_ANNUAL"),
        ("q4_component_after_signal_count", "Q4_COMPONENT_AFTER_SIGNAL"),
        ("missing_currency_count", "QUARTER_MISSING_CURRENCY"),
    ):
        if _count(quarters, key):
            problems.append({"code": code, "count": _count(quarters, key)})
    for key, code in (
        ("invalid_complete_row_count", "TTM_INVALID_COMPLETE_ROW"),
        ("available_after_signal_count", "TTM_AVAILABLE_AFTER_SIGNAL"),
        ("missing_lineage_count", "TTM_MISSING_LINEAGE"),
    ):
        if _count(ttm, key):
            problems.append({"code": code, "count": _count(ttm, key)})
    if _count(ttm, "complete_row_count") <= 0:
        warnings.append({"code": "NO_COMPLETE_TTM_ROWS"})
    for key, code in (
        ("invalid_kind_count", "EARNINGS_INVALID_KIND"),
        ("availability_mismatch_count", "EARNINGS_AVAILABILITY_MISMATCH"),
        ("invalid_revision_count", "EARNINGS_INVALID_REVISION"),
        ("ineligible_row_count", "EARNINGS_INELIGIBLE_CANONICAL_ROW"),
        ("duplicate_event_count", "EARNINGS_DUPLICATE_EVENT"),
    ):
        if _count(earnings, key):
            problems.append({"code": code, "count": _count(earnings, key)})
    for key, code in (
        ("expected_after_signal_count", "EXPECTED_EARNINGS_AFTER_SIGNAL"),
        ("reported_after_signal_count", "REPORTED_EARNINGS_AFTER_SIGNAL"),
        ("stale_recent_status_count", "STALE_RECENT_EARNINGS_STATUS"),
    ):
        if _count(earnings_context, key):
            problems.append({"code": code, "count": _count(earnings_context, key)})
    for key, code in (
        ("promotion_mode_violation_count", "VALUATION_NOT_SHADOW_ONLY"),
        ("production_change_violation_count", "VALUATION_PRODUCTION_CHANGE_ALLOWED"),
        ("price_after_signal_count", "VALUATION_PRICE_AFTER_SIGNAL"),
        ("financial_after_signal_count", "VALUATION_FINANCIAL_AFTER_SIGNAL"),
        ("negative_multiple_count", "VALUATION_NEGATIVE_MULTIPLE"),
        ("cross_currency_arithmetic_count", "VALUATION_CROSS_CURRENCY_ARITHMETIC"),
    ):
        if _count(valuation, key):
            problems.append({"code": code, "count": _count(valuation, key)})
    if _count(no_lookahead, "violation_count"):
        problems.append(
            {
                "code": "NO_LOOKAHEAD_VIOLATION",
                "count": _count(no_lookahead, "violation_count"),
            }
        )
    if _count(comparison, "promotion_violation_count"):
        problems.append(
            {
                "code": "COMPARISON_PROMOTION_ELIGIBLE",
                "count": _count(comparison, "promotion_violation_count"),
            }
        )
    for key, code in (
        ("promotion_violation_count", "INVALIDATION_PROMOTION_ELIGIBLE"),
        ("classification_violation_count", "INVALIDATION_CLASSIFICATION_MISMATCH"),
        ("recomputation_violation_count", "INVALIDATION_RECOMPUTATION_MISMATCH"),
    ):
        if _count(invalidation, key):
            problems.append({"code": code, "count": _count(invalidation, key)})

    return {
        "status": "PASS" if not problems else "FAIL",
        "problems": problems,
        "warnings": warnings,
        "hard_gate_count": len(problems),
        "warning_count": len(warnings),
    }


def current_git_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def write_evidence(document: Mapping[str, Any], output: Path | None):
    text = json.dumps(document, indent=2, sort_keys=True, default=_json_default) + "\n"
    if output is None:
        print(text, end="")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    print(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--location", default="us-east1")
    parser.add_argument("--environment", default="shadow")
    parser.add_argument("--mapping-version", required=True)
    parser.add_argument("--git-sha")
    parser.add_argument("--ci-run-id", required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.environment != "shadow":
            raise EvidenceError("WP-03 evidence capture is restricted to shadow")
        evidence = capture_evidence(
            project_id=args.project_id,
            dataset_id=args.dataset_id,
            location=args.location,
            mapping_version=args.mapping_version,
            git_sha=args.git_sha or current_git_sha(),
            ci_run_id=args.ci_run_id,
        )
        write_evidence(evidence, args.output)
        return 0 if evidence["evaluation"]["status"] == "PASS" else 2
    except (EvidenceError, OSError, ValueError, subprocess.SubprocessError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc)}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

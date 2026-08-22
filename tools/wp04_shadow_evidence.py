"""Read-only WP-04 evidence capture with official BCCh FX hard gates."""

from __future__ import annotations

import os
from typing import Any, Iterable, Mapping

from packages.common._data_contract_types import ContractError, normalize_shape
from packages.common.data_contracts import compare_schema as _strict_compare_schema
from tools import wp03_sql_policy as _sql_policy
from tools import wp04_shadow_evidence_core as _core
from tools.wp04_fx_source import (
    AVAILABILITY_POLICY,
    POLICY_VERSION as OFFICIAL_FX_POLICY_VERSION,
    PROVIDER as OFFICIAL_FX_PROVIDER,
    SERIES_ID as OFFICIAL_FX_SERIES_ID,
    SOURCE_VERSION as OFFICIAL_FX_SOURCE_VERSION,
)
from tools.wp04_secondary_source import POLICY_VERSION as SECONDARY_SOURCE_POLICY_VERSION

ROOT = _core.ROOT
PROJECT = _core.PROJECT
DATASET = _core.DATASET
MUTATING = _core.MUTATING
Wp04EvidenceError = _core.Wp04EvidenceError
canonical_json = _core.canonical_json
digest = _core.digest
validate_scope = _core.validate_scope
fqtn = _core.fqtn

CONTRACT_TABLES = (
    "market_price_raw",
    "corporate_actions_pit",
    "market_session_calendar",
    "price_source_reconciliation",
    "market_price_canonical",
    "fx_rate_raw",
    "fx_rates_pit",
)
REQUIRED_TABLES = CONTRACT_TABLES + (
    "trading_price_features_canonical_shadow",
    "trading_price_features_wp04_shadow",
    "wp04_legacy_vs_canonical_shadow",
    "audit_canonical_prices",
)
_core.CONTRACT_TABLES = CONTRACT_TABLES
_core.REQUIRED_TABLES = REQUIRED_TABLES

_BASE_BUILD_QUERIES = _core.build_queries
_BASE_EVALUATE = _core.evaluate


def read_only(sql: str) -> str:
    text = str(sql or "").strip()
    masked = _sql_policy.mask_google_sql_comments(
        text,
        mask_literals=True,
        mask_identifiers=True,
        error_cls=Wp04EvidenceError,
        label="evidence SQL",
    )
    if MUTATING.search(masked):
        raise Wp04EvidenceError("mutating SQL is forbidden in evidence capture")
    if not masked.lstrip().upper().startswith(("SELECT", "WITH")):
        raise Wp04EvidenceError("evidence SQL must begin with SELECT or WITH")
    return text


def _normalized_schema(
    actual_schema: Iterable[Mapping[str, Any]],
) -> dict[str, tuple[str, str]]:
    actual: dict[str, tuple[str, str]] = {}
    for row in actual_schema:
        name = str(row.get("name") or "")
        if not name or name in actual:
            raise ContractError(
                "actual schema contains missing or duplicate column names"
            )
        actual[name] = normalize_shape(
            str(row.get("type") or row.get("field_type") or ""),
            str(row.get("mode") or "NULLABLE"),
        )
    return actual


def compare_materialized_schema(
    contract: Mapping[str, Any],
    actual_schema: Iterable[Mapping[str, Any]],
    *,
    allow_extra_columns: bool | None = None,
) -> list[str]:
    implementation = contract.get("implementation", {})
    if implementation.get("mode") != "CODE_SCHEMA_REFERENCE":
        return _strict_compare_schema(
            contract,
            actual_schema,
            allow_extra_columns=allow_extra_columns,
        )
    expected = {
        row["name"]: normalize_shape(row["type"], row["mode"])
        for row in contract["columns"]
    }
    actual = _normalized_schema(actual_schema)
    drift: list[str] = []
    for name, (expected_type, expected_mode) in expected.items():
        observed = actual.get(name)
        if observed is None:
            drift.append(f"MISSING_COLUMN:{name}")
            continue
        actual_type, actual_mode = observed
        if actual_type != expected_type:
            drift.append(
                f"COLUMN_TYPE:{name}:expected={expected_type}:actual={actual_type}"
            )
        if actual_mode != expected_mode and not (
            expected_mode == "REQUIRED" and actual_mode == "NULLABLE"
        ):
            drift.append(
                f"COLUMN_MODE:{name}:expected={expected_mode}:actual={actual_mode}"
            )
    allow_extra = (
        bool(implementation.get("allow_additional_columns", False))
        if allow_extra_columns is None
        else bool(allow_extra_columns)
    )
    if not allow_extra:
        drift.extend(
            f"UNEXPECTED_COLUMN:{name}"
            for name in sorted(set(actual) - set(expected))
        )
    return sorted(drift)


def secondary_source_required() -> bool:
    normalized = str(
        os.environ.get("WP04_REQUIRE_SECONDARY_SOURCE", "false")
    ).strip().lower()
    if normalized in {"1", "true", "yes", "required"}:
        return True
    if normalized in {"0", "false", "no", "optional", ""}:
        return False
    raise Wp04EvidenceError(
        "WP04_REQUIRE_SECONDARY_SOURCE must be true/false or required/optional"
    )


def build_queries(project: str, dataset: str) -> dict[str, str]:
    queries = dict(_BASE_BUILD_QUERIES(project, dataset))
    raw_table = fqtn(project, dataset, "market_price_raw")
    fx_raw_table = fqtn(project, dataset, "fx_rate_raw")
    fx_table = fqtn(project, dataset, "fx_rates_pit")
    queries["raw_summary"] = read_only(
        queries["raw_summary"].replace(
            "COUNTIF(asset_type = 'FX') AS fx_row_count,",
            "COUNTIF(asset_type = 'FX') AS fx_row_count,\n"
            "            COUNTIF(provider = 'YAHOO' AND asset_type = 'FX') "
            "AS diagnostic_fx_ohlc_row_count,",
        )
    )
    queries["official_fx_raw_summary"] = read_only(
        f"""
          SELECT
            COUNT(*) AS row_count,
            COUNT(*) - COUNT(DISTINCT fx_rate_revision_id)
              AS duplicate_revision_count,
            COUNTIF(
              rate <= 0
              OR base_currency != 'USD'
              OR quote_currency != 'CLP'
              OR status_code != 'OK'
              OR quality_status != 'CURRENT_SNAPSHOT_NO_VINTAGE'
              OR backtest_eligible
            ) AS invalid_rate_count,
            COUNTIF(
              provider != 'BCCH_BDE'
              OR series_id != 'F073.TCO.PRE.Z.D'
              OR source_version != 'bcch-bde-rest-v1'
              OR source_timezone != 'America/Santiago'
            ) AS invalid_source_count,
            COUNTIF(first_observed_at IS NULL)
              AS missing_first_observed_count,
            COUNTIF(available_at < first_observed_at)
              AS retroactive_availability_count,
            COUNTIF(available_at != first_observed_at)
              AS availability_mismatch_count,
            COUNTIF(source_reference_date >= rate_date)
              AS reference_date_invalid_count,
            COUNTIF(
              source_published_at >= TIMESTAMP(rate_date, source_timezone)
            ) AS publication_not_prior_count,
            COUNTIF(first_observed_at != ingested_at OR available_at > ingested_at)
              AS available_after_ingestion_count,
            COUNTIF(
              availability_policy !=
                'wp04-bcch-vintage-availability-v2'
            ) AS policy_invalid_count,
            COUNTIF(
              backtest_eligible
              OR publication_evidence_uri IS NOT NULL
              OR publication_evidence_sha256 IS NOT NULL
              OR publication_evidence_at IS NOT NULL
            ) AS snapshot_presented_as_vintage_count,
            COUNTIF(
              backtest_eligible
              AND (
                publication_evidence_uri IS NULL
                OR publication_evidence_sha256 IS NULL
                OR publication_evidence_at IS NULL
              )
            ) AS eligible_without_publication_evidence_count,
            COUNTIF(production_change_allowed)
              AS production_change_violation_count
          FROM {fx_raw_table}
        """
    )
    queries["fx_summary"] = read_only(
        f"""
          SELECT
            COUNT(*) AS row_count,
            COUNT(*) - COUNT(DISTINCT fx_rate_id)
              AS duplicate_rate_id_count,
            (
              SELECT COUNT(*)
              FROM (
                SELECT source_rate_revision_id
                FROM {fx_table}
                GROUP BY source_rate_revision_id
                HAVING COUNT(*) > 1
              )
            ) AS duplicate_rate_key_count,
            COUNTIF(
              rate <= 0
              OR base_currency != 'USD'
              OR quote_currency != 'CLP'
              OR provider != 'BCCH_BDE'
              OR series_id != 'F073.TCO.PRE.Z.D'
              OR source_version != 'bcch-bde-rest-v1'
              OR quality_status != 'CURRENT_SNAPSHOT_NO_VINTAGE'
              OR availability_policy !=
                'wp04-bcch-vintage-availability-v2'
              OR first_observed_at IS NULL
              OR available_at != first_observed_at
              OR first_observed_at != ingested_at
              OR backtest_eligible
              OR publication_evidence_uri IS NOT NULL
              OR publication_evidence_sha256 IS NOT NULL
              OR publication_evidence_at IS NOT NULL
              OR available_at > ingested_at
            ) AS invalid_rate_count,
            COUNTIF(available_at < first_observed_at)
              AS revision_used_before_observation_count,
            COUNTIF(production_change_allowed)
              AS production_change_violation_count
          FROM {fx_table}
        """
    )
    if raw_table not in queries["raw_summary"]:
        raise Wp04EvidenceError("raw summary lost its shadow-scoped source")
    return queries


def _count(row: Mapping[str, Any], key: str) -> int:
    return int(row.get(key) or 0)


def evaluate(
    *,
    results: Mapping[str, Mapping[str, Any]],
    schema_drift: Mapping[str, list[str]],
) -> dict[str, Any]:
    if "official_fx_raw_summary" not in results:
        raise Wp04EvidenceError(
            "missing evidence query results: ['official_fx_raw_summary']"
        )
    result = dict(_BASE_EVALUATE(results=results, schema_drift=schema_drift))
    required = secondary_source_required()
    problems = [
        problem
        for problem in result.get("problems", [])
        if problem.get("code") != "FX_ROWS_MISSING"
        and not (
            not required and problem.get("code") == "STOOQ_ROWS_MISSING"
        )
    ]
    warnings = list(result.get("warnings", []))
    if not required and any(
        problem.get("code") == "STOOQ_ROWS_MISSING"
        for problem in result.get("problems", [])
    ):
        warnings.append(
            {
                "code": "SECONDARY_SOURCE_UNAVAILABLE_OPTIONAL",
                "provider": "STOOQ",
                "policy_version": SECONDARY_SOURCE_POLICY_VERSION,
            }
        )

    diagnostic_rows = _count(
        results.get("raw_summary", {}), "diagnostic_fx_ohlc_row_count"
    )
    if diagnostic_rows:
        warnings.append(
            {
                "code": "DIAGNOSTIC_FX_OHLC_ROWS_PRESENT",
                "count": diagnostic_rows,
                "eligible": False,
            }
        )

    official = results["official_fx_raw_summary"]
    if _count(official, "row_count") <= 0:
        problems.append({"code": "OFFICIAL_FX_RAW_EMPTY"})
    for key, code in (
        ("duplicate_revision_count", "OFFICIAL_FX_DUPLICATE_REVISION"),
        ("invalid_rate_count", "OFFICIAL_FX_INVALID_RATE"),
        ("invalid_source_count", "OFFICIAL_FX_INVALID_RATE"),
        ("availability_mismatch_count", "OFFICIAL_FX_AVAILABILITY_MISMATCH"),
        ("missing_first_observed_count", "OFFICIAL_FX_FIRST_OBSERVED_MISSING"),
        ("retroactive_availability_count", "OFFICIAL_FX_RETROACTIVE_AVAILABILITY"),
        ("reference_date_invalid_count", "OFFICIAL_FX_REFERENCE_DATE_INVALID"),
        ("publication_not_prior_count", "OFFICIAL_FX_PUBLICATION_NOT_PRIOR"),
        ("available_after_ingestion_count", "OFFICIAL_FX_AVAILABLE_AFTER_INGESTION"),
        ("policy_invalid_count", "OFFICIAL_FX_POLICY_INVALID"),
        ("snapshot_presented_as_vintage_count", "OFFICIAL_FX_SNAPSHOT_AS_VINTAGE"),
        (
            "eligible_without_publication_evidence_count",
            "OFFICIAL_FX_ELIGIBLE_WITHOUT_PUBLICATION_EVIDENCE",
        ),
        ("production_change_violation_count", "OFFICIAL_FX_PRODUCTION_CHANGE"),
    ):
        count = _count(official, key)
        if count:
            problems.append({"code": code, "count": count})

    fx_summary = results.get("fx_summary", {})
    revision_before_observation = _count(
        fx_summary, "revision_used_before_observation_count"
    )
    if revision_before_observation:
        problems.append(
            {
                "code": "OFFICIAL_FX_REVISION_USED_BEFORE_OBSERVATION",
                "count": revision_before_observation,
            }
        )

    result.update(
        {
            "status": "PASS" if not problems else "FAIL",
            "hard_gate_count": len(problems),
            "warning_count": len(warnings),
            "problems": problems,
            "warnings": warnings,
            "secondary_source_policy": {
                "policy_version": SECONDARY_SOURCE_POLICY_VERSION,
                "provider": "STOOQ",
                "required": required,
                "unavailable_behavior": (
                    "FAIL_CLOSED" if required else "WARN_AND_SINGLE_SOURCE"
                ),
                "production_change_allowed": False,
            },
            "official_fx_source_policy": {
                "policy_version": OFFICIAL_FX_POLICY_VERSION,
                "provider": OFFICIAL_FX_PROVIDER,
                "series_id": OFFICIAL_FX_SERIES_ID,
                "source_version": OFFICIAL_FX_SOURCE_VERSION,
                "availability_policy": AVAILABILITY_POLICY,
                "required": True,
                "production_change_allowed": False,
            },
        }
    )
    return result


_core.read_only = read_only
_core.compare_schema = compare_materialized_schema
_core.build_queries = build_queries
_core.evaluate = evaluate
capture = _core.capture
current_sha = _core.current_sha
write_output = _core.write_output
main = _core.main


def __getattr__(name: str) -> Any:
    try:
        return getattr(_core, name)
    except AttributeError as exc:
        raise AttributeError(name) from exc


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_core)))


if __name__ == "__main__":
    raise SystemExit(main())

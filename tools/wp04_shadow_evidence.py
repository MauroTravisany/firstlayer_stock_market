"""Materialization-aware facade for WP-04 shadow evidence capture.

The reviewed implementation remains in :mod:`tools.wp04_shadow_evidence_core`.
This facade adds read-only SQL safety, CTAS schema compatibility, optional Stooq
handling, and mandatory Banco Central de Chile USD/CLP evidence gates.
"""

from __future__ import annotations

import os
from typing import Any, Iterable, Mapping

from packages.common._data_contract_types import ContractError, normalize_shape
from packages.common.data_contracts import compare_schema as _strict_compare_schema
from tools import wp03_sql_policy as _sql_policy
from tools import wp04_shadow_evidence_core as _core
from tools.wp04_bcch_fx_source import POLICY_VERSION as FX_REFERENCE_POLICY_VERSION
from tools.wp04_secondary_source import POLICY_VERSION as SECONDARY_SOURCE_POLICY_VERSION

ROOT = _core.ROOT
PROJECT = _core.PROJECT
DATASET = _core.DATASET
MUTATING = _core.MUTATING
CONTRACT_TABLES = _core.CONTRACT_TABLES
REQUIRED_TABLES = _core.REQUIRED_TABLES
Wp04EvidenceError = _core.Wp04EvidenceError
canonical_json = _core.canonical_json
digest = _core.digest
validate_scope = _core.validate_scope
fqtn = _core.fqtn
_BASE_BUILD_QUERIES = _core.build_queries
_BASE_EVALUATE = _core.evaluate

def read_only(sql: str) -> str:
    text = str(sql or "").strip()
    masked = _sql_policy.mask_google_sql_comments(text, mask_literals=True, mask_identifiers=True, error_cls=Wp04EvidenceError, label="evidence SQL")
    if MUTATING.search(masked):
        raise Wp04EvidenceError("mutating SQL is forbidden in evidence capture")
    if not masked.lstrip().upper().startswith(("SELECT", "WITH")):
        raise Wp04EvidenceError("evidence SQL must begin with SELECT or WITH")
    return text

def _normalized_schema(actual_schema: Iterable[Mapping[str, Any]]) -> dict[str, tuple[str, str]]:
    actual: dict[str, tuple[str, str]] = {}
    for row in actual_schema:
        name = str(row.get("name") or "")
        if not name or name in actual:
            raise ContractError("actual schema contains missing or duplicate column names")
        actual[name] = normalize_shape(str(row.get("type") or row.get("field_type") or ""), str(row.get("mode") or "NULLABLE"))
    return actual

def compare_materialized_schema(contract: Mapping[str, Any], actual_schema: Iterable[Mapping[str, Any]], *, allow_extra_columns: bool | None = None) -> list[str]:
    implementation = contract.get("implementation", {})
    if implementation.get("mode") != "CODE_SCHEMA_REFERENCE":
        return _strict_compare_schema(contract, actual_schema, allow_extra_columns=allow_extra_columns)
    expected = {row["name"]: normalize_shape(row["type"], row["mode"]) for row in contract["columns"]}
    actual = _normalized_schema(actual_schema)
    drift: list[str] = []
    for name, (expected_type, expected_mode) in expected.items():
        observed = actual.get(name)
        if observed is None:
            drift.append(f"MISSING_COLUMN:{name}")
            continue
        actual_type, actual_mode = observed
        if actual_type != expected_type:
            drift.append(f"COLUMN_TYPE:{name}:expected={expected_type}:actual={actual_type}")
        if actual_mode != expected_mode and not (expected_mode == "REQUIRED" and actual_mode == "NULLABLE"):
            drift.append(f"COLUMN_MODE:{name}:expected={expected_mode}:actual={actual_mode}")
    allow_extra = bool(implementation.get("allow_additional_columns", False)) if allow_extra_columns is None else bool(allow_extra_columns)
    if not allow_extra:
        drift.extend(f"UNEXPECTED_COLUMN:{name}" for name in sorted(set(actual) - set(expected)))
    return sorted(drift)

def secondary_source_required() -> bool:
    normalized = str(os.environ.get("WP04_REQUIRE_SECONDARY_SOURCE", "false")).strip().lower()
    if normalized in {"1", "true", "yes", "required"}:
        return True
    if normalized in {"0", "false", "no", "optional", ""}:
        return False
    raise Wp04EvidenceError("WP04_REQUIRE_SECONDARY_SOURCE must be true/false or required/optional")

def build_queries(project: str, dataset: str) -> dict[str, str]:
    queries = dict(_BASE_BUILD_QUERIES(project, dataset))
    raw = queries["raw_summary"].replace(
        "COUNTIF(provider = 'STOOQ') AS stooq_row_count,",
        "COUNTIF(provider = 'STOOQ') AS stooq_row_count,\n            COUNTIF(provider = 'BCCH_BDE') AS bcch_row_count,\n            COUNTIF(provider = 'BCCH_BDE' AND (provider_symbol != 'F073.TCO.PRE.Z.D' OR quality_status != 'RAW_REFERENCE_RATE_VALIDATED' OR open IS NOT NULL OR high IS NOT NULL OR low IS NOT NULL OR close IS NOT NULL OR volume IS NOT NULL OR adjusted_close IS NULL OR adjusted_close <= 0 OR available_at < bar_end)) AS invalid_bcch_reference_count,",
    )
    queries["raw_summary"] = read_only(raw)
    fx = queries["fx_summary"].replace(
        "COUNTIF(production_change_allowed) AS production_change_violation_count",
        "COUNTIF(production_change_allowed) AS production_change_violation_count,\n            COUNTIF(provider = 'BCCH_BDE') AS bcch_provider_count,\n            COUNTIF(quality_status = 'OFFICIAL_REFERENCE_RATE') AS official_quality_count",
    )
    queries["fx_summary"] = read_only(fx)
    return queries

def evaluate(*, results: Mapping[str, Mapping[str, Any]], schema_drift: Mapping[str, list[str]]) -> dict[str, Any]:
    result = dict(_BASE_EVALUATE(results=results, schema_drift=schema_drift))
    required = secondary_source_required()
    problems = list(result.get("problems", []))
    warnings = list(result.get("warnings", []))
    if not required:
        retained, moved = [], False
        for problem in problems:
            if problem.get("code") == "STOOQ_ROWS_MISSING":
                moved = True
            else:
                retained.append(problem)
        if moved:
            warnings.append({"code": "SECONDARY_SOURCE_UNAVAILABLE_OPTIONAL", "provider": "STOOQ", "policy_version": SECONDARY_SOURCE_POLICY_VERSION})
        problems = retained
    raw = results.get("raw_summary", {})
    if int(raw.get("bcch_row_count") or 0) <= 0:
        problems.append({"code": "OFFICIAL_USD_CLP_SOURCE_MISSING", "provider": "BCCH_BDE"})
    invalid_reference = int(raw.get("invalid_bcch_reference_count") or 0)
    if invalid_reference:
        problems.append({"code": "INVALID_OFFICIAL_USD_CLP_REFERENCE", "count": invalid_reference})
    fx = results.get("fx_summary", {})
    if int(fx.get("bcch_provider_count") or 0) <= 0:
        problems.append({"code": "FX_RATE_NOT_SOURCED_FROM_BCCH"})
    if int(fx.get("official_quality_count") or 0) <= 0:
        problems.append({"code": "OFFICIAL_FX_QUALITY_MISSING"})
    result.update({
        "status": "PASS" if not problems else "FAIL",
        "hard_gate_count": len(problems),
        "warning_count": len(warnings),
        "problems": problems,
        "warnings": warnings,
        "secondary_source_policy": {"policy_version": SECONDARY_SOURCE_POLICY_VERSION, "provider": "STOOQ", "required": required, "unavailable_behavior": "FAIL_CLOSED" if required else "WARN_AND_SINGLE_SOURCE", "production_change_allowed": False},
        "fx_reference_policy": {"policy_version": FX_REFERENCE_POLICY_VERSION, "provider": "BCCH_BDE", "required": True, "production_change_allowed": False},
    })
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

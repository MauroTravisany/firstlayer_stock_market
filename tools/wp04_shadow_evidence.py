"""Materialization-aware facade for WP-04 shadow evidence capture.

The reviewed query/evaluation implementation remains in
:mod:`tools.wp04_shadow_evidence_core`. This facade fixes two policy surfaces:
read-only SQL classification and BigQuery CTAS schema-mode comparison.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

from packages.common._data_contract_types import ContractError, normalize_shape
from packages.common.data_contracts import compare_schema as _strict_compare_schema
from tools import wp03_sql_policy as _sql_policy
from tools import wp04_shadow_evidence_core as _core


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


def read_only(sql: str) -> str:
    """Require one non-mutating SELECT/WITH statement.

    Mutations are checked before statement classification so an explicit MERGE,
    CREATE, UPDATE, or similar command reports the security violation rather
    than the less useful "must begin with SELECT" error. Comments, literals and
    quoted identifiers are masked for the keyword scan.
    """

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
    """Compare observed BigQuery schema under the declared materialization.

    BigQuery CTAS/Dataform relation outputs commonly expose scalar expressions
    as NULLABLE even when a contract requires non-null values through Dataform
    assertions. For ``CODE_SCHEMA_REFERENCE`` only that scalar
    REQUIRED-to-NULLABLE relaxation is accepted. Data types, REPEATED fields,
    missing columns, duplicate names and additional-column policy remain
    strict. Explicit ``DATAFORM_CREATE`` tables retain exact shape comparison.
    """

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
        mode_relaxed = expected_mode == "REQUIRED" and actual_mode == "NULLABLE"
        if actual_mode != expected_mode and not mode_relaxed:
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


# Functions defined in the retained core resolve their module globals at call
# time. Patch the two policy hooks before exporting the public API.
_core.read_only = read_only
_core.compare_schema = compare_materialized_schema

build_queries = _core.build_queries
evaluate = _core.evaluate
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

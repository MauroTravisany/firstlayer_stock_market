"""Comment-aware facade for the WP-03 compiled SQL schema graph.

The reviewed schema-graph implementation is preserved in
:mod:`tools.wp03_compiled_sql_semantic_preflight_core`. This facade patches its
lexical policy checks so valid GoogleSQL comments are ignored for statement
classification and safety scanning, while the original SQL remains unchanged
for hashing and BigQuery dry-run/schema validation.
"""

from __future__ import annotations

from typing import Any

from tools import wp03_compiled_sql_semantic_preflight_core as _core
from tools import wp03_sql_policy as _sql_policy


SQL_POLICY_VERSION = _sql_policy.SQL_POLICY_VERSION
SCHEMA_GRAPH_PASS_STATUS = "ALL_COMPILED_ACTIONS_SCHEMA_GRAPH_PASS"
VALIDATION_DATASET_ONLY_FIELD = "validation_dataset_only"

# Keep the public inventory explicit. Besides making the operational contract
# auditable without following an import, this preserves the repository's static
# coverage gate. The equality assertion prevents facade/core drift.
REQUIRED_OUTPUTS = (
    "financial_statements_pit_raw",
    "financial_statements_pit",
    "financial_quarters_pit",
    "financial_ttm_pit",
    "earnings_events_pit",
    "trading_financial_context_pit",
    "trading_earnings_context_pit",
    "portfolio_valuation_pit_shadow",
    "trading_historical_context_pit",
    "wp03_legacy_vs_pit_shadow",
    "wp03_legacy_invalidation",
    "audit_no_lookahead",
)
if REQUIRED_OUTPUTS != _core.REQUIRED_OUTPUTS:
    raise RuntimeError("WP-03 facade/core required-output inventory drift")


def _assert_select_only(action: Any) -> None:
    _sql_policy.assert_select_only(
        action,
        select_pattern=_core.SELECT_SQL,
        mutating_pattern=_core.MUTATING_SQL,
        error_cls=_core.SemanticPreflightError,
    )


def _assert_no_operational_write(
    action: Any,
    *,
    project_id: str,
    operational_dataset: str,
) -> None:
    _sql_policy.assert_no_operational_write(
        action,
        project_id=project_id,
        operational_dataset=operational_dataset,
        operational_write_pattern=_core.OPERATIONAL_WRITE,
        error_cls=_core.SemanticPreflightError,
    )


def _assert_raw_operation_scope(action: Any) -> None:
    _sql_policy.assert_raw_operation_scope(
        action,
        raw_output=_core.RAW_OUTPUT,
        forbidden_statement_pattern=_core.FORBIDDEN_OPERATION_STATEMENT,
        create_table_target_pattern=_core.CREATE_TABLE_TARGET,
        error_cls=_core.SemanticPreflightError,
    )


# Core functions resolve these names from their defining module at runtime.
# Replacing the three policy hooks therefore fixes both direct invocation of
# this facade and the stable public entrypoint without duplicating the graph
# implementation.
_core._assert_select_only = _assert_select_only
_core._assert_no_operational_write = _assert_no_operational_write
_core._assert_raw_operation_scope = _assert_raw_operation_scope


ACKNOWLEDGEMENT = _core.ACKNOWLEDGEMENT
RAW_OUTPUT = _core.RAW_OUTPUT
ALLOWED_OPERATIONAL_INPUTS = _core.ALLOWED_OPERATIONAL_INPUTS
SemanticPreflightError = _core.SemanticPreflightError
Target = _core.Target
CompiledAction = _core.CompiledAction
verify_clean_checkout = _core.verify_clean_checkout
validate_scope = _core.validate_scope
load_actions_document = _core.load_actions_document
parse_action = _core.parse_action
build_plan = _core.build_plan
verify_plan_checksum = _core.verify_plan_checksum
execute_schema_graph = _core.execute_schema_graph
main = _core.main


def __getattr__(name: str) -> Any:
    """Preserve compatibility with every reviewed core attribute."""

    try:
        return getattr(_core, name)
    except AttributeError as exc:
        raise AttributeError(name) from exc


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_core)))


if __name__ == "__main__":
    raise SystemExit(main())

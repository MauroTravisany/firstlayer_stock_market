"""Comment-aware facade for the WP-03 compiled SQL schema graph.

The reviewed schema-graph implementation is preserved in
:mod:`tools.wp03_compiled_sql_semantic_preflight_core`. This facade patches its
lexical policy checks so valid GoogleSQL comments are ignored for statement
classification and safety scanning, while the original SQL remains unchanged
for hashing and BigQuery dry-run/schema validation.

It also models the native Dataform action types explicitly: the raw store is an
``operations`` action, ten materialized models are ``relation`` actions, and
``audit_no_lookahead`` is a first-class required ``assertion`` action.
"""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Mapping, Sequence

from tools import wp03_compiled_sql_semantic_preflight_core as _core
from tools import wp03_join_policy as _join_policy
from tools import wp03_sql_policy as _sql_policy


SQL_POLICY_VERSION = _sql_policy.SQL_POLICY_VERSION
JOIN_KEY_POLICY_VERSION = _join_policy.JOIN_KEY_POLICY_VERSION
SCHEMA_ACTION_POLICY_VERSION = "wp03-native-action-types-v1"
SCHEMA_GRAPH_PASS_STATUS = "ALL_COMPILED_ACTIONS_SCHEMA_GRAPH_PASS"
VALIDATION_DATASET_ONLY_FIELD = "validation_dataset_only"
AUDIT_ASSERTION = "audit_no_lookahead"

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

REQUIRED_ACTION_TYPES = {
    name: (
        "operations"
        if name == _core.RAW_OUTPUT
        else "assertion"
        if name == AUDIT_ASSERTION
        else "relation"
    )
    for name in REQUIRED_OUTPUTS
}

_CORE_BUILD_PLAN = _core.build_plan
_CORE_MAIN = _core.main


def _assert_select_only(action: Any) -> None:
    _sql_policy.assert_select_only(
        action,
        select_pattern=_core.SELECT_SQL,
        mutating_pattern=_core.MUTATING_SQL,
        error_cls=_core.SemanticPreflightError,
    )
    if action.action_type in {"relation", "assertion"}:
        _join_policy.assert_explicit_join_predicates(
            action.sql[0],
            error_cls=_core.SemanticPreflightError,
            label=action.target.key,
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


def _audit_action_match(
    action_rows: Sequence[Mapping[str, Any]],
) -> tuple[int, Mapping[str, Any], Any]:
    matches = [
        (index, row)
        for index, row in enumerate(action_rows)
        if str((row.get("target") or {}).get("name") or "").strip()
        == AUDIT_ASSERTION
    ]
    if len(matches) != 1:
        raise _core.SemanticPreflightError(
            f"required action {AUDIT_ASSERTION} must appear exactly once; "
            f"found {len(matches)}"
        )
    index, row = matches[0]
    return index, row, _core.parse_action(row)


def _relation_proxy_for_assertion(row: Mapping[str, Any]) -> dict[str, Any]:
    """Create an in-memory proxy understood by the reviewed legacy planner.

    The proxy is never written to disk and never changes the compiled SQL. It is
    used only to reuse the reviewed topology, dependency and scope logic. The
    returned plan and required-action map are restored to the native assertion
    type before hashing or execution.
    """

    proxy = deepcopy(dict(row))
    assertion_body = proxy.pop("assertion")
    relation_body = dict(assertion_body)
    relation_body.pop("parentAction", None)
    relation_body.setdefault("relationType", "VIEW")
    proxy["relation"] = relation_body
    return proxy


def _rehash_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    document = dict(plan)
    document.pop("plan_checksum", None)
    document["plan_checksum"] = _core._sha256_json(document)
    return document


def _decorate_native_action_plan(
    plan: Mapping[str, Any],
    required: Mapping[str, Any],
    assertions: Sequence[Any],
) -> dict[str, Any]:
    action_type_counts = {
        action_type: sum(
            1 for action in required.values() if action.action_type == action_type
        )
        for action_type in ("operations", "relation", "assertion")
    }
    document = dict(plan)
    document.update(
        {
            "schema_action_policy_version": SCHEMA_ACTION_POLICY_VERSION,
            "join_key_policy_version": JOIN_KEY_POLICY_VERSION,
            "required_action_count": len(required),
            "required_action_types": {
                name: required[name].action_type for name in REQUIRED_OUTPUTS
            },
            "required_action_type_counts": action_type_counts,
            "required_assertion_count": action_type_counts["assertion"],
            "generated_assertion_count": len(assertions),
            "total_assertion_count": (
                action_type_counts["assertion"] + len(assertions)
            ),
            # Retain the pre-existing field for backward-compatible evidence.
            # It continues to mean generated assertions attached to required
            # models; the required audit assertion is counted separately above.
            "assertion_count": len(assertions),
        }
    )
    return _rehash_plan(document)


def _build_plan_native(
    action_rows: Sequence[Mapping[str, Any]],
    *,
    strict_native_types: bool,
    project_id: str,
    operational_dataset: str,
    validation_dataset: str,
    compilation_result: str,
    git_sha: str,
    actions_document_sha256: str,
):
    rows = tuple(action_rows)
    audit_index, audit_row, audit_action = _audit_action_match(rows)

    if strict_native_types and audit_action.action_type != "assertion":
        raise _core.SemanticPreflightError(
            f"required action {AUDIT_ASSERTION} must compile as assertion; "
            f"found {audit_action.action_type}"
        )

    if audit_action.action_type == "assertion":
        proxy_rows = list(rows)
        proxy_rows[audit_index] = _relation_proxy_for_assertion(audit_row)
        plan, required, generated_assertions = _CORE_BUILD_PLAN(
            proxy_rows,
            project_id=project_id,
            operational_dataset=operational_dataset,
            validation_dataset=validation_dataset,
            compilation_result=compilation_result,
            git_sha=git_sha,
            actions_document_sha256=actions_document_sha256,
        )
        required = dict(required)
        required[AUDIT_ASSERTION] = audit_action

        required_rows = []
        for name in REQUIRED_OUTPUTS:
            action = required[name]
            required_rows.append(action.as_plan_row())
        plan = {
            **dict(plan),
            "required_actions": required_rows,
        }
    else:
        # Compatibility path for the original unit-test fixture. The CLI never
        # uses this path: main() installs the strict native-type planner.
        plan, required, generated_assertions = _CORE_BUILD_PLAN(
            rows,
            project_id=project_id,
            operational_dataset=operational_dataset,
            validation_dataset=validation_dataset,
            compilation_result=compilation_result,
            git_sha=git_sha,
            actions_document_sha256=actions_document_sha256,
        )

    # A top-level required assertion belongs in required_actions and in the
    # topological layers. It must not also appear in the generated assertion
    # collection, otherwise it would be dry-run twice and counted twice.
    required_target_keys = {action.target.key for action in required.values()}
    generated_assertions = tuple(
        action
        for action in generated_assertions
        if action.target.key not in required_target_keys
    )

    decorated = _decorate_native_action_plan(
        plan,
        required,
        generated_assertions,
    )
    return decorated, required, generated_assertions


def build_plan(
    action_rows: Sequence[Mapping[str, Any]],
    *,
    project_id: str,
    operational_dataset: str,
    validation_dataset: str,
    compilation_result: str,
    git_sha: str,
    actions_document_sha256: str,
):
    """Build a plan while retaining compatibility with the original fixture."""

    return _build_plan_native(
        action_rows,
        strict_native_types=False,
        project_id=project_id,
        operational_dataset=operational_dataset,
        validation_dataset=validation_dataset,
        compilation_result=compilation_result,
        git_sha=git_sha,
        actions_document_sha256=actions_document_sha256,
    )


def build_plan_strict(
    action_rows: Sequence[Mapping[str, Any]],
    *,
    project_id: str,
    operational_dataset: str,
    validation_dataset: str,
    compilation_result: str,
    git_sha: str,
    actions_document_sha256: str,
):
    """Build the operator plan and enforce native Dataform action types."""

    return _build_plan_native(
        action_rows,
        strict_native_types=True,
        project_id=project_id,
        operational_dataset=operational_dataset,
        validation_dataset=validation_dataset,
        compilation_result=compilation_result,
        git_sha=git_sha,
        actions_document_sha256=actions_document_sha256,
    )


def main() -> int:
    """Run the reviewed CLI with strict native Dataform action typing."""

    previous = _core.build_plan
    _core.build_plan = build_plan_strict
    try:
        return _CORE_MAIN()
    finally:
        _core.build_plan = previous


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
verify_plan_checksum = _core.verify_plan_checksum
execute_schema_graph = _core.execute_schema_graph


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

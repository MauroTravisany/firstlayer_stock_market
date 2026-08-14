"""Validate the compiled WP-04 Dataform graph in an isolated schema-only dataset.

The command is read-only by default. ``--execute`` is permitted only against a
new, empty BigQuery dataset whose name contains ``shadow`` and ``schema`` and
whose labels are ``environment=shadow``, ``work_package=wp04`` and
``purpose=compiled_sql_validation``. It creates three empty contract tables and
zero-row views solely to let BigQuery type-check the complete graph.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any, Mapping, Sequence

from tools import wp03_compiled_sql_semantic_preflight_core as core
from tools import wp03_join_policy as join_policy
from tools import wp03_sql_policy as sql_policy

REPO_ROOT = Path(__file__).resolve().parents[1]
ACKNOWLEDGEMENT = "WP04_SCHEMA_VALIDATION_WRITE"
SCHEMA_ACTION_POLICY_VERSION = "wp04-native-action-types-v1"
JOIN_KEY_POLICY_VERSION = "wp04-explicit-join-keys-v1"
PASS_STATUS = "ALL_COMPILED_ACTIONS_SCHEMA_GRAPH_PASS"
EXPECTED_TYPES = {
    "market_price_raw": "operations",
    "corporate_actions_pit": "operations",
    "market_session_calendar": "operations",
    "price_source_reconciliation": "relation",
    "market_price_canonical": "relation",
    "fx_rates_pit": "relation",
    "trading_price_features_canonical_shadow": "relation",
    "trading_price_features_wp04_shadow": "relation",
    "wp04_legacy_vs_canonical_shadow": "relation",
    "audit_canonical_prices": "assertion",
}
REQUIRED_ACTIONS = tuple(EXPECTED_TYPES)
OPERATIONS = tuple(name for name, kind in EXPECTED_TYPES.items() if kind == "operations")
RELATIONS = tuple(name for name, kind in EXPECTED_TYPES.items() if kind == "relation")
REQUIRED_ASSERTIONS = tuple(name for name, kind in EXPECTED_TYPES.items() if kind == "assertion")
ALLOWED_OPERATIONAL_INPUTS = frozenset({"trading_price_features"})
PROJECT_ID = re.compile(r"^[A-Za-z][A-Za-z0-9-]{4,62}$")
DATASET_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,1023}$")
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
SELECT_SQL = re.compile(r"^\s*(?:WITH\b|SELECT\b)", re.IGNORECASE | re.DOTALL)


class Wp04SchemaCheckError(ValueError):
    """The compiled graph or validation scope violates a hard gate."""


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def verify_clean_checkout(expected_git_sha: str) -> str:
    try:
        return core.verify_clean_checkout(expected_git_sha)
    except (ValueError, core.SemanticPreflightError) as exc:
        raise Wp04SchemaCheckError(str(exc)) from exc


def validate_scope(project_id: str, operational_dataset: str, validation_dataset: str) -> tuple[str, str, str]:
    project = str(project_id or "").strip()
    operational = str(operational_dataset or "").strip()
    validation = str(validation_dataset or "").strip()
    if not PROJECT_ID.fullmatch(project):
        raise Wp04SchemaCheckError("project_id is invalid")
    if not DATASET_ID.fullmatch(operational):
        raise Wp04SchemaCheckError("operational_dataset is invalid")
    if not DATASET_ID.fullmatch(validation):
        raise Wp04SchemaCheckError("validation_dataset is invalid")
    if "shadow" not in validation.lower() or "schema" not in validation.lower():
        raise Wp04SchemaCheckError("validation_dataset must contain both 'shadow' and 'schema'")
    if validation == operational:
        raise Wp04SchemaCheckError("validation_dataset cannot equal operational_dataset")
    return project, operational, validation


def load_actions_document(path: Path) -> tuple[dict[str, Any], ...]:
    try:
        return core.load_actions_document(path)
    except (ValueError, core.SemanticPreflightError) as exc:
        raise Wp04SchemaCheckError(str(exc)) from exc


def _assert_action_policy(action: core.CompiledAction, project: str, operational: str) -> None:
    if action.action_type in {"relation", "assertion"}:
        sql_policy.assert_select_only(
            action,
            select_pattern=SELECT_SQL,
            mutating_pattern=core.MUTATING_SQL,
            error_cls=Wp04SchemaCheckError,
        )
        join_policy.assert_explicit_join_predicates(
            action.sql[0], error_cls=Wp04SchemaCheckError, label=action.target.key
        )
    elif action.action_type == "operations":
        sql_policy.assert_raw_operation_scope(
            action,
            raw_output=action.target.name,
            forbidden_statement_pattern=core.FORBIDDEN_OPERATION_STATEMENT,
            create_table_target_pattern=core.CREATE_TABLE_TARGET,
            error_cls=Wp04SchemaCheckError,
        )
    sql_policy.assert_no_operational_write(
        action,
        project_id=project,
        operational_dataset=operational,
        operational_write_pattern=core.OPERATIONAL_WRITE,
        error_cls=Wp04SchemaCheckError,
    )


def _generated_assertion(action: core.CompiledAction, required_keys: frozenset[str]) -> bool:
    if action.action_type != "assertion" or action.target.name in REQUIRED_ASSERTIONS:
        return False
    if action.parent_action and action.parent_action.key in required_keys:
        return True
    return any(dep.key in required_keys for dep in action.dependency_targets)


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
    project, operational, validation = validate_scope(project_id, operational_dataset, validation_dataset)
    if not SHA40.fullmatch(str(git_sha or "")):
        raise Wp04SchemaCheckError("git_sha must be a full lowercase commit SHA")
    if not SHA256.fullmatch(str(actions_document_sha256 or "")):
        raise Wp04SchemaCheckError("actions_document_sha256 must be SHA-256")
    if not str(compilation_result or "").strip():
        raise Wp04SchemaCheckError("compilation_result is required")
    try:
        actions = tuple(core.parse_action(row) for row in action_rows)
    except (ValueError, core.SemanticPreflightError) as exc:
        raise Wp04SchemaCheckError(str(exc)) from exc
    if len({action.target.key for action in actions}) != len(actions):
        raise Wp04SchemaCheckError("compilation actions contain duplicate targets")

    required: dict[str, core.CompiledAction] = {}
    for name in REQUIRED_ACTIONS:
        matches = [action for action in actions if action.target.name == name]
        if len(matches) != 1:
            raise Wp04SchemaCheckError(f"required action {name} must appear exactly once; found {len(matches)}")
        action = matches[0]
        if action.action_type != EXPECTED_TYPES[name]:
            raise Wp04SchemaCheckError(
                f"required action {name} must be {EXPECTED_TYPES[name]}; compiled as {action.action_type}"
            )
        if action.disabled:
            raise Wp04SchemaCheckError("required action {name} is disabled")
        if action.target.database != project or action.target.schema != validation:
            raise Wp04SchemaCheckError(f"required action {name} must target {project}.{validation}")
        _assert_action_policy(action, project, operational)
        required[name] = action

    target_to_name = {action.target.key: name for name, action in required.items()}
    required_keys = frozenset(target_to_name)
    generated = tuple(action for action in actions if _generated_assertion(action, required_keys))
    for action in generated:
        if action.disabled:
            raise Wp04SchemaCheckError(f"generated assertion {action.target.key} is disabled")
        if action.target.database != project or action.target.schema != validation:
            raise Wp04SchemaCheckError(f"assertion {action.target.key} must target {project}.{validation}")
        _assert_action_policy(action, project, operational)

    for action in tuple(required.values()) + generated:
        for dep in action.dependency_targets:
            if dep.key in required_keys:
                continue
            if dep.database == project and dep.schema == operational and dep.name in ALLOWED_OPERATIONAL_INPUTS:
                continue
            raise Wp04SchemaCheckError(f"action.target.key} has unauthorized dependency {dep.key}")

    completed = set(OPERATIONS)
    pending = set(RELATIONS)
    layers: list[list[str]] = [sorted(OPERATIONS)]
    while pending:
        layer = sorted(
            name
            for name in pending
            if all(target_to_name.get(dep.key) in completed or dep.key not in required_keys for dep in required[name].dependency_targets)
        )
        if not layer:
            unresolved = {
                name: [dep.key for dep in required[name].dependency_targets if target_to_name.get(dep.key) in pending]
                for name in sorted(pending)
            }
            raise Wp04SchemaCheckError(f"WP-04 relation graph is cyclic or unresolved: {unresolved}")
        layers.append(layer)
        completed.update(layer)
        pending.difference_update(layer)

    plan = {
        "schema_version": 1,
        "operation": "WP0;kºwµç
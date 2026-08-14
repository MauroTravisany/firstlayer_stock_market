"""Fail-closed schema-only BigQuery validation for the compiled WP-04 graph."""
from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import wp03_compiled_sql_semantic_preflight_core as core
from tools import wp03_join_policy as joins
from tools import wp03_sql_policy as sql_policy

ACK = "WP04_SCHEMA_VALIDATION_WRITE"
PASS = "ALL_COMPILED_ACTIONS_SCHEMA_GRAPH_PASS"
POLICY = "wp04-native-action-types-v1"
JOIN_POLICY = "wp04-explicit-join-keys-v1"
EXPECTED = {
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
OPERATIONS = tuple(k for k, v in EXPECTED.items() if v == "operations")
RELATIONS = tuple(k for k, v in EXPECTED.items() if v == "relation")
REQUIRED_ASSERTIONS = tuple(k for k, v in EXPECTED.items() if v == "assertion")
REQUIRED_ACTIONS = tuple(EXPECTED)
ALLOWED_INPUTS = frozenset({"trading_price_features"})
NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,1023}$")
PROJECT = re.compile(r"^[A-Za-z][A-Za-z0-9-]{4,62}$")
SHA40 = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
SELECT = re.compile(r"^\s*(?:WITH\b|SELECT\b)", re.I | re.S)


class Error(ValueError):
    pass


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def verify_clean_checkout(expected: str) -> str:
    try:
        return core.verify_clean_checkout(expected)
    except (ValueError, core.SemanticPreflightError) as exc:
        raise Error(str(exc)) from exc


def validate_scope(project: str, operational: str, validation: str):
    project, operational, validation = map(str.strip, (project, operational, validation))
    if not PROJECT.fullmatch(project):
        raise Error("project_id is invalid")
    if not NAME.fullmatch(operational) or not NAME.fullmatch(validation):
        raise Error("dataset identifier is invalid")
    if operational == validation or "shadow" not in validation.lower() or "schema" not in validation.lower():
        raise Error("validation_dataset must be distinct and contain shadow and schema")
    return project, operational, validation


def load_actions_document(path: Path):
    try:
        return core.load_actions_document(path)
    except (ValueError, core.SemanticPreflightError) as exc:
        raise Error(str(exc)) from exc


def check_sql(action, project: str, operational: str):
    if action.action_type in {"relation", "assertion"}:
        sql_policy.assert_select_only(action, select_pattern=SELECT, mutating_pattern=core.MUTATING_SQL, error_cls=Error)
        joins.assert_explicit_join_predicates(action.sql[0], error_cls=Error, label=action.target.key)
    elif action.action_type == "operations":
        sql_policy.assert_raw_operation_scope(
            action,
            raw_output=action.target.name,
            forbidden_statement_pattern=core.FORBIDDEN_OPERATION_STATEMENT,
            create_table_target_pattern=core.CREATE_TABLE_TARGET,
            error_cls=Error,
        )
    sql_policy.assert_no_operational_write(
        action,
        project_id=project,
        operational_dataset=operational,
        operational_write_pattern=core.OPERATIONAL_WRITE,
        error_cls=Error,
    )


def generated_assertion(action, required_keys):
    return (
        action.action_type == "assertion"
        and action.target.name not in REQUIRED_ASSERTIONS
        and (
            (action.parent_action and action.parent_action.key in required_keys)
            or any(dep.key in required_keys for dep in action.dependency_targets)
        )
    )


def build_plan(rows: Sequence[Mapping[str, Any]], *, project_id: str, operational_dataset: str,
               validation_dataset: str, compilation_result: str, git_sha: str,
               actions_document_sha256: str):
    project, operational, validation = validate_scope(project_id, operational_dataset, validation_dataset)
    if not SHA40.fullmatch(git_sha):
        raise Error("git_sha must be a full lowercase commit SHA")
    if not SHA256.fullmatch(actions_document_sha256):
        raise Error("actions_document_sha256 must be SHA-256")
    if not compilation_result.strip():
        raise Error("compilation_result is required")
    try:
        actions = tuple(core.parse_action(row) for row in rows)
    except (ValueError, core.SemanticPreflightError) as exc:
        raise Error(str(exc)) from exc
    if len({a.target.key for a in actions}) != len(actions):
        raise Error("compiled actions contain duplicate targets")

    required = {}
    for name, kind in EXPECTED.items():
        matches = [a for a in actions if a.target.name == name]
        if len(matches) != 1:
            raise Error(f"required action {name} must appear exactly once; found {len(matches)}")
        action = matches[0]
        if action.action_type != kind:
            raise Error(f"required action {name} must be {kind}; compiled as {action.action_type}")
        if action.disabled or action.target.database != project or action.target.schema != validation:
            raise Error(f"required action {name} must be enabled and target {project}.{validation}")
        check_sql(action, project, operational)
        required[name] = action

    target_names = {a.target.key: name for name, a in required.items()}
    required_keys = frozenset(target_names)
    generated = tuple(a for a in actions if generated_assertion(a, required_keys))
    for action in generated:
        if action.disabled or action.target.database != project or action.target.schema != validation:
            raise Error(f"generated assertion {action.target.key} is outside validation scope")
        check_sql(action, project, operational)

    for action in tuple(required.values()) + generated:
        for dep in action.dependency_targets:
            if dep.key in required_keys:
                continue
            if dep.database == project and dep.schema == operational and dep.name in ALLOWED_INPUTS:
                continue
            raise Error(f"{action.target.key} has unauthorized dependency {dep.key}")

    completed, pending = set(OPERATIONS), set(RELATIONS)
    layers = [sorted(OPERATIONS)]
    while pending:
        layer = sorted(name for name in pending if all(
            target_names.get(dep.key) in completed or dep.key not in required_keys
            for dep in required[name].dependency_targets
        ))
        if not layer:
            raise Error(f"WP-04 relation graph is cyclic or unresolved: {sorted(pending)}")
        layers.append(layer)
        completed.update(layer)
        pending.difference_update(layer)

    plan = {
        "schema_version": 1,
        "operation": "WP04_COMPILED_SQL_SCHEMA_GRAPH",
        "mode": "PLAN",
        "schema_action_policy_version": POLICY,
        "join_key_policy_version": JOIN_POLICY,
        "git_sha": git_sha,
        "compilation_result": compilation_result,
        "project_id": project,
        "operational_dataset": operational,
        "validation_dataset": validation,
        "required_action_count": len(required),
        "required_action_type_counts": {"operations": len(OPERATIONS), "relation": len(RELATIONS), "assertion": len(REQUIRED_ASSERTIONS)},
        "required_action_types": dict(EXPECTED),
        "required_assertion_count": len(REQUIRED_ASSERTIONS),
        "generated_assertion_count": len(generated),
        "total_assertion_count": len(REQUIRED_ASSERTIONS) + len(generated),
        "allowed_operational_inputs": sorted(ALLOWED_INPUTS),
        "layers": layers,
        "actions_document_sha256": actions_document_sha256,
        "required_actions": [required[name].as_plan_row() for name in REQUIRED_ACTIONS],
        "generated_assertions": [a.as_plan_row() for a in sorted(generated, key=lambda x: x.target.key)],
        "production_change_allowed": False,
    }
    plan["plan_checksum"] = digest(plan)
    return plan, required, generated


def verify_plan_checksum(plan, expected: str):
    expected = str(expected or "").strip().lower()
    if not SHA256.fullmatch(expected) or expected != plan.get("plan_checksum"):
        raise Error("plan checksum mismatch or invalid expected_plan_checksum")
    return expected

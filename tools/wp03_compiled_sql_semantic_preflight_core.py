"""Validate every compiled WP-03 action in an isolated schema-only graph.

The command is read-only by default. ``--execute`` is permitted only against a
clean, labelled validation dataset. Execution creates one empty raw placeholder
and zero-row logical views so downstream compiled queries can be validated
without materializing research data.

It never writes to the operational dataset, the real WP-03 shadow dataset,
Dataform production, Cloud Run, schedulers, IAM, Secret Manager or a broker.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import yaml


REPO_ROOT = Path(__file__).resolve().parents[1]
ACKNOWLEDGEMENT = "WP03_SCHEMA_VALIDATION_WRITE"
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
RAW_OUTPUT = "financial_statements_pit_raw"
ALLOWED_OPERATIONAL_INPUTS = frozenset(
    {
        "macro_earnings_calendar",
        "trading_price_features",
        "asset_profile",
        "valuation_model_profile",
        "trading_historical_context",
        "portfolio_valuation_daily",
    }
)
PROJECT_ID = re.compile(r"^[A-Za-z][A-Za-z0-9-]{4,62}$")
DATASET_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,1023}$")
GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
SHA256 = re.compile(r"^[0-9a-f]{64}$")
SELECT_SQL = re.compile(r"^\s*(?:WITH\b|SELECT\b)", re.IGNORECASE | re.DOTALL)
MUTATING_SQL = re.compile(
    r"\b(?:INSERT|UPDATE|DELETE|MERGE|CREATE|ALTER|DROP|TRUNCATE|CALL|EXPORT|LOAD|GRANT|REVOKE)\b",
    re.IGNORECASE,
)
OPERATIONAL_WRITE = re.compile(
    r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM|MERGE\s+INTO|"
    r"CREATE(?:\s+OR\s+REPLACE)?\s+(?:TABLE|VIEW)|ALTER\s+TABLE|DROP\s+(?:TABLE|VIEW)|TRUNCATE\s+TABLE)"
    r"[\s\S]{0,300}?`?([A-Za-z][A-Za-z0-9-]{4,62})\.([A-Za-z_][A-Za-z0-9_]*)\.",
    re.IGNORECASE,
)
CREATE_TABLE_TARGET = re.compile(
    r"\bCREATE\s+TABLE(?:\s+IF\s+NOT\s+EXISTS)?\s+`([^`]+)`",
    re.IGNORECASE,
)
FORBIDDEN_OPERATION_STATEMENT = re.compile(
    r"\b(?:INSERT|UPDATE|DELETE|MERGE|ALTER|DROP|TRUNCATE|CALL|EXPORT|LOAD|GRANT|REVOKE)\b",
    re.IGNORECASE,
)


class SemanticPreflightError(ValueError):
    """Compilation actions or validation scope violate a hard gate."""


@dataclass(frozen=True, order=True)
class Target:
    database: str
    schema: str
    name: str

    @classmethod
    def from_mapping(cls, payload: Mapping[str, Any], label: str) -> "Target":
        if not isinstance(payload, Mapping):
            raise SemanticPreflightError(f"{label} target is missing")
        values = {
            key: str(payload.get(key) or "").strip()
            for key in ("database", "schema", "name")
        }
        if not all(values.values()):
            raise SemanticPreflightError(f"{label} target is incomplete")
        return cls(**values)

    @property
    def key(self) -> str:
        return f"{self.database}.{self.schema}.{self.name}"

    @property
    def quoted(self) -> str:
        return f"`{self.key}`"

    def as_dict(self) -> dict[str, str]:
        return {
            "database": self.database,
            "schema": self.schema,
            "name": self.name,
        }


@dataclass(frozen=True)
class CompiledAction:
    action_type: str
    target: Target
    canonical_target: Target | None
    file_path: str
    sql: tuple[str, ...]
    dependency_targets: tuple[Target, ...]
    disabled: bool
    parent_action: Target | None = None

    @property
    def sql_sha256(self) -> str:
        return _sha256_json(list(self.sql))

    def as_plan_row(self) -> dict[str, Any]:
        return {
            "action_type": self.action_type,
            "target": self.target.as_dict(),
            "canonical_target": (
                self.canonical_target.as_dict() if self.canonical_target else None
            ),
            "file_path": self.file_path,
            "sql_sha256": self.sql_sha256,
            "dependency_targets": [
                target.as_dict() for target in self.dependency_targets
            ],
            "disabled": self.disabled,
            "parent_action": (
                self.parent_action.as_dict() if self.parent_action else None
            ),
        }


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )


def _sha256_json(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _run_git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def verify_clean_checkout(expected_git_sha: str) -> str:
    expected = str(expected_git_sha or "").strip().lower()
    if not GIT_SHA.fullmatch(expected):
        raise SemanticPreflightError(
            "expected_git_sha must be a full lowercase commit SHA"
        )
    current = _run_git("rev-parse", "HEAD").lower()
    if current != expected:
        raise SemanticPreflightError(
            f"Git SHA mismatch: expected {expected}, current checkout is {current}"
        )
    if _run_git("status", "--porcelain", "--untracked-files=all"):
        raise SemanticPreflightError(
            "compiled SQL preflight requires a clean checkout"
        )
    return current


def validate_scope(
    project_id: str,
    operational_dataset: str,
    validation_dataset: str,
) -> tuple[str, str, str]:
    project = str(project_id or "").strip()
    operational = str(operational_dataset or "").strip()
    validation = str(validation_dataset or "").strip()
    if not PROJECT_ID.fullmatch(project):
        raise SemanticPreflightError("project_id is invalid")
    if not DATASET_ID.fullmatch(operational):
        raise SemanticPreflightError("operational_dataset is invalid")
    if not DATASET_ID.fullmatch(validation):
        raise SemanticPreflightError("validation_dataset is invalid")
    lowered = validation.lower()
    if "shadow" not in lowered or "schema" not in lowered:
        raise SemanticPreflightError(
            "validation_dataset must contain both 'shadow' and 'schema'"
        )
    if validation == operational:
        raise SemanticPreflightError(
            "validation_dataset cannot equal operational_dataset"
        )
    return project, operational, validation


def load_actions_document(path: Path) -> tuple[dict[str, Any], ...]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SemanticPreflightError(f"unable to read actions JSON: {exc}") from exc

    if isinstance(payload, list):
        rows = payload
    elif isinstance(payload, Mapping):
        rows = payload.get("compilationResultActions")
        if rows is None and isinstance(payload.get("pages"), list):
            rows = [
                action
                for page in payload["pages"]
                for action in page.get("compilationResultActions", [])
            ]
    else:
        rows = None
    if not isinstance(rows, list) or not rows:
        raise SemanticPreflightError(
            "actions JSON must contain compilationResultActions"
        )
    if any(not isinstance(row, Mapping) for row in rows):
        raise SemanticPreflightError("every compilation action must be an object")
    return tuple(dict(row) for row in rows)


def _targets(payload: Any, label: str) -> tuple[Target, ...]:
    if payload is None:
        return ()
    if not isinstance(payload, list):
        raise SemanticPreflightError(f"{label} must be a list")
    return tuple(
        Target.from_mapping(item, f"{label}[{index}]")
        for index, item in enumerate(payload)
    )


def parse_action(payload: Mapping[str, Any]) -> CompiledAction:
    target = Target.from_mapping(payload.get("target"), "action")
    canonical_payload = payload.get("canonicalTarget")
    canonical = (
        Target.from_mapping(canonical_payload, "canonical")
        if canonical_payload
        else None
    )
    file_path = str(payload.get("filePath") or "").strip()
    compiled_keys = [
        key
        for key in ("relation", "operations", "assertion", "declaration")
        if isinstance(payload.get(key), Mapping)
    ]
    if len(compiled_keys) != 1:
        raise SemanticPreflightError(
            f"{target.key} must have exactly one supported compiled object"
        )
    action_type = compiled_keys[0]
    body = payload[action_type]
    dependency_targets = _targets(
        body.get("dependencyTargets"), f"{target.key}.dependencyTargets"
    )
    disabled = bool(body.get("disabled", False))
    parent_action = (
        Target.from_mapping(body.get("parentAction"), "parentAction")
        if body.get("parentAction")
        else None
    )
    if action_type == "relation":
        sql = (str(body.get("selectQuery") or "").strip(),)
    elif action_type == "operations":
        queries = body.get("queries")
        if not isinstance(queries, list):
            raise SemanticPreflightError(
                f"{target.key}.operations.queries must be a list"
            )
        sql = tuple(str(query or "").strip() for query in queries)
    elif action_type == "assertion":
        sql = (str(body.get("selectQuery") or "").strip(),)
    else:
        sql = ()
    if action_type != "declaration" and (not sql or any(not query for query in sql)):
        raise SemanticPreflightError(f"{target.key} has empty compiled SQL")
    return CompiledAction(
        action_type=action_type,
        target=target,
        canonical_target=canonical,
        file_path=file_path,
        sql=sql,
        dependency_targets=dependency_targets,
        disabled=disabled,
        parent_action=parent_action,
    )


def _assert_select_only(action: CompiledAction) -> None:
    if action.action_type not in {"relation", "assertion"}:
        return
    query = action.sql[0]
    if not SELECT_SQL.search(query):
        raise SemanticPreflightError(
            f"{action.target.key} compiled query must begin with SELECT or WITH"
        )
    if MUTATING_SQL.search(query):
        raise SemanticPreflightError(
            f"{action.target.key} contains mutating SQL"
        )


def _assert_no_operational_write(
    action: CompiledAction,
    *,
    project_id: str,
    operational_dataset: str,
) -> None:
    for query in action.sql:
        for match in OPERATIONAL_WRITE.finditer(query):
            if (
                match.group(1) == project_id
                and match.group(2) == operational_dataset
            ):
                raise SemanticPreflightError(
                    f"{action.target.key} attempts to mutate the operational dataset"
                )



def _assert_raw_operation_scope(action: CompiledAction) -> None:
    if action.action_type != "operations":
        return
    if action.target.name != RAW_OUTPUT:
        raise SemanticPreflightError(
            f"unexpected operations output {action.target.key}"
        )
    if len(action.sql) != 1:
        raise SemanticPreflightError(
            f"{RAW_OUTPUT} must compile to exactly one CREATE TABLE statement"
        )
    query = action.sql[0]
    if FORBIDDEN_OPERATION_STATEMENT.search(query):
        raise SemanticPreflightError(
            f"{RAW_OUTPUT} operations SQL contains a forbidden statement"
        )
    targets = CREATE_TABLE_TARGET.findall(query)
    if targets != [action.target.key]:
        raise SemanticPreflightError(
            f"{RAW_OUTPUT} must create only {action.target.key}; found {targets}"
        )

def _is_required_assertion(
    action: CompiledAction,
    required_target_keys: frozenset[str],
) -> bool:
    if action.action_type != "assertion":
        return False
    if action.parent_action and action.parent_action.key in required_target_keys:
        return True
    return any(
        dependency.key in required_target_keys
        for dependency in action.dependency_targets
    )


def build_plan(
    action_rows: Sequence[Mapping[str, Any]],
    *,
    project_id: str,
    operational_dataset: str,
    validation_dataset: str,
    compilation_result: str,
    git_sha: str,
    actions_document_sha256: str,
) -> tuple[dict[str, Any], dict[str, CompiledAction], tuple[CompiledAction, ...]]:
    project, operational, validation = validate_scope(
        project_id, operational_dataset, validation_dataset
    )
    if not GIT_SHA.fullmatch(str(git_sha or "")):
        raise SemanticPreflightError("git_sha must be a full lowercase commit SHA")
    if not SHA256.fullmatch(str(actions_document_sha256 or "")):
        raise SemanticPreflightError("actions_document_sha256 must be SHA-256")
    if not str(compilation_result or "").strip():
        raise SemanticPreflightError("compilation_result is required")
    actions = tuple(parse_action(row) for row in action_rows)
    if len({action.target.key for action in actions}) != len(actions):
        raise SemanticPreflightError("compilation actions contain duplicate targets")

    required: dict[str, CompiledAction] = {}
    for name in REQUIRED_OUTPUTS:
        matches = [action for action in actions if action.target.name == name]
        if len(matches) != 1:
            raise SemanticPreflightError(
                f"required output {name} must appear exactly once; found {len(matches)}"
            )
        action = matches[0]
        if action.action_type not in {"relation", "operations"}:
            raise SemanticPreflightError(
                f"required output {name} has unsupported type {action.action_type}"
            )
        if action.disabled:
            raise SemanticPreflightError(f"required output {name} is disabled")
        if action.target.database != project or action.target.schema != validation:
            raise SemanticPreflightError(
                f"required output {name} must target {project}.{validation}"
            )
        if name == RAW_OUTPUT and action.action_type != "operations":
            raise SemanticPreflightError(
                f"{RAW_OUTPUT} must remain an operations output"
            )
        if name != RAW_OUTPUT and action.action_type != "relation":
            raise SemanticPreflightError(
                f"{name} must compile as a relation"
            )
        _assert_select_only(action)
        _assert_raw_operation_scope(action)
        _assert_no_operational_write(
            action,
            project_id=project,
            operational_dataset=operational,
        )
        required[name] = action

    required_target_to_name = {
        action.target.key: name for name, action in required.items()
    }
    required_target_keys = frozenset(required_target_to_name)
    assertions = tuple(
        action
        for action in actions
        if _is_required_assertion(action, required_target_keys)
    )
    for action in assertions:
        if action.disabled:
            raise SemanticPreflightError(
                f"required assertion {action.target.key} is disabled"
            )
        if action.target.database != project or action.target.schema != validation:
            raise SemanticPreflightError(
                f"assertion {action.target.key} must target {project}.{validation}"
            )
        _assert_select_only(action)
        _assert_no_operational_write(
            action,
            project_id=project,
            operational_dataset=operational,
        )

    for action in tuple(required.values()) + assertions:
        for dependency in action.dependency_targets:
            if dependency.key in required_target_keys:
                continue
            if (
                dependency.database == project
                and dependency.schema == operational
                and dependency.name in ALLOWED_OPERATIONAL_INPUTS
            ):
                continue
            raise SemanticPreflightError(
                f"{action.target.key} has unauthorized dependency {dependency.key}"
            )

    relation_names = set(REQUIRED_OUTPUTS) - {RAW_OUTPUT}
    completed = {RAW_OUTPUT}
    layers: list[list[str]] = []
    while relation_names:
        layer = sorted(
            name
            for name in relation_names
            if all(
                required_target_to_name.get(dependency.key) in completed
                or dependency.key not in required_target_keys
                for dependency in required[name].dependency_targets
            )
        )
        if not layer:
            unresolved = {
                name: [
                    dependency.key
                    for dependency in required[name].dependency_targets
                    if required_target_to_name.get(dependency.key) in relation_names
                ]
                for name in sorted(relation_names)
            }
            raise SemanticPreflightError(
                f"WP-03 relation graph is cyclic or unresolved: {unresolved}"
            )
        layers.append(layer)
        completed.update(layer)
        relation_names.difference_update(layer)

    plan_payload = {
        "schema_version": 1,
        "operation": "WP03_COMPILED_SQL_SCHEMA_GRAPH",
        "mode": "PLAN",
        "git_sha": git_sha,
        "compilation_result": compilation_result,
        "project_id": project,
        "operational_dataset": operational,
        "validation_dataset": validation,
        "required_output_count": len(required),
        "assertion_count": len(assertions),
        "allowed_operational_inputs": sorted(ALLOWED_OPERATIONAL_INPUTS),
        "layers": layers,
        "actions_document_sha256": actions_document_sha256,
        "required_actions": [
            required[name].as_plan_row() for name in REQUIRED_OUTPUTS
        ],
        "assertions": [
            action.as_plan_row()
            for action in sorted(assertions, key=lambda item: item.target.key)
        ],
        "production_change_allowed": False,
    }
    plan_payload["plan_checksum"] = _sha256_json(plan_payload)
    return plan_payload, required, assertions


def verify_plan_checksum(plan: Mapping[str, Any], expected: str) -> str:
    expected_checksum = str(expected or "").strip().lower()
    if not SHA256.fullmatch(expected_checksum):
        raise SemanticPreflightError(
            "expected_plan_checksum must be lowercase SHA-256"
        )
    actual = str(plan.get("plan_checksum") or "").lower()
    if actual != expected_checksum:
        raise SemanticPreflightError(
            f"plan checksum mismatch: expected {expected_checksum}, actual {actual}"
        )
    return actual


def _load_bigquery():
    try:
        from google.cloud import bigquery
    except ImportError as exc:
        raise SemanticPreflightError(
            "google-cloud-bigquery is required only for --execute"
        ) from exc
    return bigquery


def _contract_schema(contract_path: Path, bigquery) -> list[Any]:
    try:
        document = yaml.safe_load(contract_path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise SemanticPreflightError(f"unable to load raw contract: {exc}") from exc
    columns = document.get("columns") if isinstance(document, Mapping) else None
    if not isinstance(columns, list) or not columns:
        raise SemanticPreflightError("raw contract columns are missing")
    schema = []
    seen = set()
    for column in columns:
        if not isinstance(column, Mapping):
            raise SemanticPreflightError("raw contract column is invalid")
        name = str(column.get("name") or "").strip()
        field_type = str(column.get("type") or "").strip().upper()
        mode = str(column.get("mode") or "NULLABLE").strip().upper()
        if not name or name in seen:
            raise SemanticPreflightError(
                "raw contract column names must be non-empty and unique"
            )
        if mode not in {"NULLABLE", "REQUIRED", "REPEATED"}:
            raise SemanticPreflightError(
                f"raw contract mode is invalid for {name}: {mode}"
            )
        seen.add(name)
        schema.append(bigquery.SchemaField(name, field_type, mode=mode))
    return schema


def _schema_shape(schema: Iterable[Any]) -> list[tuple[str, str, str]]:
    return [
        (
            str(field.name),
            str(field.field_type).upper(),
            str(field.mode).upper(),
        )
        for field in schema
    ]


def _error_payload(exc: Exception) -> dict[str, Any]:
    errors = getattr(exc, "errors", None)
    return {
        "type": type(exc).__name__,
        "message": str(exc),
        "errors": errors if isinstance(errors, list) else None,
    }


def execute_schema_graph(
    *,
    plan: Mapping[str, Any],
    required: Mapping[str, CompiledAction],
    assertions: Sequence[CompiledAction],
    contract_path: Path,
    location: str,
    client: Any | None = None,
    bigquery_module: Any | None = None,
) -> dict[str, Any]:
    project = str(plan["project_id"])
    validation_dataset = str(plan["validation_dataset"])
    bigquery = bigquery_module if bigquery_module is not None else _load_bigquery()
    if client is None:
        client = bigquery.Client(project=project, location=location)

    dataset_id = f"{project}.{validation_dataset}"
    dataset = client.get_dataset(dataset_id)
    dataset_location = str(getattr(dataset, "location", "") or "")
    if dataset_location.lower() != str(location).lower():
        raise SemanticPreflightError(
            f"validation dataset location is {dataset_location}, expected {location}"
        )
    labels = dict(getattr(dataset, "labels", None) or {})
    expected_labels = {
        "environment": "shadow",
        "work_package": "wp03",
        "purpose": "compiled_sql_validation",
    }
    label_problems = {
        key: {"expected": value, "actual": labels.get(key)}
        for key, value in expected_labels.items()
        if labels.get(key) != value
    }
    if label_problems:
        raise SemanticPreflightError(
            f"validation dataset labels are invalid: {label_problems}"
        )

    existing = list(client.list_tables(dataset))
    if existing:
        raise SemanticPreflightError(
            "validation dataset must be empty; use a new timestamped dataset"
        )

    raw_target = required[RAW_OUTPUT].target
    schema = _contract_schema(contract_path, bigquery)
    raw_table = bigquery.Table(raw_target.key, schema=schema)
    raw_table.labels = {
        "environment": "shadow",
        "work_package": "wp03",
        "purpose": "compiled_sql_validation",
    }
    client.create_table(raw_table)
    created_objects = [
        {
            "target": raw_target.key,
            "object_type": "EMPTY_CONTRACT_TABLE",
            "schema_sha256": _sha256_json(_schema_shape(schema)),
        }
    ]
    required_target_to_name = {
        action.target.key: name for name, action in required.items()
    }
    available = {RAW_OUTPUT}
    action_results: list[dict[str, Any]] = []

    job_config = bigquery.QueryJobConfig(
        dry_run=True,
        use_query_cache=False,
    )
    for layer_index, layer in enumerate(plan["layers"], start=1):
        for name in layer:
            action = required[name]
            internal_dependencies = {
                required_target_to_name[dependency.key]
                for dependency in action.dependency_targets
                if dependency.key in required_target_to_name
            }
            blocked_by = sorted(internal_dependencies - available)
            if blocked_by:
                action_results.append(
                    {
                        "name": name,
                        "target": action.target.key,
                        "layer": layer_index,
                        "status": "BLOCKED_BY_FAILED_DEPENDENCY",
                        "blocked_by": blocked_by,
                        "sql_sha256": action.sql_sha256,
                    }
                )
                continue
            query = action.sql[0]
            try:
                dry_job = client.query(
                    query,
                    job_config=job_config,
                    location=location,
                )
                total_bytes = int(
                    getattr(dry_job, "total_bytes_processed", 0) or 0
                )
                query_body = query.rstrip().removesuffix(";").rstrip()
                zero_row_query = (
                    "SELECT * FROM (\n"
                    f"{query_body}\n"
                    ") WHERE FALSE"
                )
                view_sql = (
                    f"CREATE OR REPLACE VIEW {action.target.quoted} AS\n"
                    f"{zero_row_query}"
                )
                view_job = client.query(view_sql, location=location)
                view_job.result(timeout=300)
                available.add(name)
                created_objects.append(
                    {
                        "target": action.target.key,
                        "object_type": "ZERO_ROW_SCHEMA_VIEW",
                        "sql_sha256": action.sql_sha256,
                        "zero_row_guard": True,
                    }
                )
                action_results.append(
                    {
                        "name": name,
                        "target": action.target.key,
                        "layer": layer_index,
                        "status": "PASS",
                        "dry_run_total_bytes_processed": total_bytes,
                        "sql_sha256": action.sql_sha256,
                    }
                )
            except Exception as exc:  # BigQuery exception surfaces vary by client.
                action_results.append(
                    {
                        "name": name,
                        "target": action.target.key,
                        "layer": layer_index,
                        "status": "FAIL",
                        "sql_sha256": action.sql_sha256,
                        "error": _error_payload(exc),
                    }
                )

    assertion_results: list[dict[str, Any]] = []
    for action in sorted(assertions, key=lambda item: item.target.key):
        internal_dependencies = {
            required_target_to_name[dependency.key]
            for dependency in action.dependency_targets
            if dependency.key in required_target_to_name
        }
        blocked_by = sorted(internal_dependencies - available)
        if blocked_by:
            assertion_results.append(
                {
                    "target": action.target.key,
                    "status": "BLOCKED_BY_FAILED_DEPENDENCY",
                    "blocked_by": blocked_by,
                    "sql_sha256": action.sql_sha256,
                }
            )
            continue
        try:
            dry_job = client.query(
                action.sql[0],
                job_config=job_config,
                location=location,
            )
            assertion_results.append(
                {
                    "target": action.target.key,
                    "status": "PASS",
                    "dry_run_total_bytes_processed": int(
                        getattr(dry_job, "total_bytes_processed", 0) or 0
                    ),
                    "sql_sha256": action.sql_sha256,
                }
            )
        except Exception as exc:
            assertion_results.append(
                {
                    "target": action.target.key,
                    "status": "FAIL",
                    "sql_sha256": action.sql_sha256,
                    "error": _error_payload(exc),
                }
            )

    failed_actions = [
        result
        for result in action_results
        if result["status"] != "PASS"
    ]
    failed_assertions = [
        result
        for result in assertion_results
        if result["status"] != "PASS"
    ]
    status = (
        "ALL_COMPILED_ACTIONS_SCHEMA_GRAPH_PASS"
        if not failed_actions and not failed_assertions
        else "FAIL"
    )
    return {
        **dict(plan),
        "mode": "EXECUTED_SCHEMA_ONLY_VALIDATION",
        "location": location,
        "dataset_labels": labels,
        "created_objects": created_objects,
        "action_results": action_results,
        "assertion_results": assertion_results,
        "failed_action_count": len(failed_actions),
        "failed_assertion_count": len(failed_assertions),
        "status": status,
        "validation_dataset_only": True,
        "production_change_allowed": False,
    }


def _write_json(document: Mapping[str, Any], output: Path | None) -> None:
    text = json.dumps(document, indent=2, sort_keys=True, default=str) + "\n"
    if output is None:
        print(text, end="")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    print(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--actions-json", type=Path, required=True)
    parser.add_argument("--expected-git-sha", required=True)
    parser.add_argument("--compilation-result", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--operational-dataset", required=True)
    parser.add_argument("--validation-dataset", required=True)
    parser.add_argument("--location", default="us-east1")
    parser.add_argument("--environment", default="shadow")
    parser.add_argument(
        "--contract",
        type=Path,
        default=REPO_ROOT / "contracts" / "financial_statements_pit_raw.yaml",
    )
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--expected-plan-checksum")
    parser.add_argument("--acknowledge-validation-write")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        if args.environment != "shadow":
            raise SemanticPreflightError(
                "compiled SQL preflight is restricted to environment=shadow"
            )
        git_sha = verify_clean_checkout(args.expected_git_sha)
        action_rows = load_actions_document(args.actions_json)
        actions_document_sha256 = hashlib.sha256(
            args.actions_json.read_bytes()
        ).hexdigest()
        plan, required, assertions = build_plan(
            action_rows,
            project_id=args.project_id,
            operational_dataset=args.operational_dataset,
            validation_dataset=args.validation_dataset,
            compilation_result=args.compilation_result,
            git_sha=git_sha,
            actions_document_sha256=actions_document_sha256,
        )
        result: Mapping[str, Any] = plan
        if args.execute:
            if args.acknowledge_validation_write != ACKNOWLEDGEMENT:
                raise SemanticPreflightError(
                    "--execute requires --acknowledge-validation-write "
                    f"{ACKNOWLEDGEMENT}"
                )
            if not args.expected_plan_checksum:
                raise SemanticPreflightError(
                    "--execute requires --expected-plan-checksum from a prior plan"
                )
            verify_plan_checksum(plan, args.expected_plan_checksum)
            result = execute_schema_graph(
                plan=plan,
                required=required,
                assertions=assertions,
                contract_path=args.contract,
                location=args.location,
            )
        _write_json(result, args.output)
        return 0 if result.get("status") != "FAIL" else 2
    except (
        OSError,
        SemanticPreflightError,
        subprocess.SubprocessError,
        ValueError,
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

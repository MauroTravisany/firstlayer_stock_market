"""Execute the fail-closed WP-04 compiled SQL schema graph."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.wp04_schema_policy import (
    ACK,
    OPERATIONS,
    PASS,
    REQUIRED_ACTIONS,
    REQUIRED_ASSERTIONS,
    Error,
    build_plan,
    digest,
    load_actions_document,
    verify_clean_checkout,
    verify_plan_checksum,
)

ACKNOWLEDGEMENT = ACK
PASS_STATUS = PASS
OPERATION_ACTIONS = OPERATIONS
Wp04SchemaCheckError = Error


def load_bigquery():
    try:
        from google.cloud import bigquery
    except ImportError as exc:
        raise Error("google-cloud-bigquery is required only for --execute") from exc
    return bigquery


def err(exc: Exception):
    return {"type": type(exc).__name__, "message": str(exc), "errors": getattr(exc, "errors", None)}


def execute_schema_graph(*, plan, required, generated_assertions, location: str, client=None, bigquery_module=None):
    project, validation = plan["project_id"], plan["validation_dataset"]
    bq = bigquery_module or load_bigquery()
    client = client or bq.Client(project=project, location=location)
    dataset = client.get_dataset(f"{project}.{validation}")
    labels = dict(getattr(dataset, "labels", None) or {})
    expected_labels = {"environment": "shadow", "work_package": "wp04", "purpose": "compiled_sql_validation"}
    if str(getattr(dataset, "location", "")).lower() != location.lower():
        raise Error("validation dataset location mismatch")
    if any(labels.get(k) != v for k, v in expected_labels.items()):
        raise Error(f"validation dataset labels are invalid: {labels}")
    if list(client.list_tables(dataset)):
        raise Error("validation dataset must be empty")

    target_names = {a.target.key: name for name, a in required.items()}
    available, created, action_results = set(), [], []
    dry = bq.QueryJobConfig(dry_run=True, use_query_cache=False)
    for layer_index, layer in enumerate(plan["layers"], 1):
        for name in layer:
            action = required[name]
            deps = {target_names[d.key] for d in action.dependency_targets if d.key in target_names}
            blocked = sorted(deps - available)
            if blocked:
                action_results.append({"name": name, "target": action.target.key, "status": "BLOCKED_BY_FAILED_DEPENDENCY", "blocked_by": blocked, "sql_sha256": action.sql_sha256})
                continue
            try:
                if action.action_type == "operations":
                    job = client.query(action.sql[0], location=location)
                    job.result(timeout=300)
                    table = client.get_table(action.target.key)
                    created.append({"target": action.target.key, "object_type": "EMPTY_CONTRACT_TABLE", "schema_sha256": digest([(f.name, f.field_type, f.mode) for f in table.schema])})
                    total = int(getattr(job, "total_bytes_processed", 0) or 0)
                else:
                    job = client.query(action.sql[0], job_config=dry, location=location)
                    total = int(getattr(job, "total_bytes_processed", 0) or 0)
                    body = action.sql[0].rstrip().removesuffix(";").rstrip()
                    view = client.query(
                        f"CREATE OR REPLACE VIEW {action.target.quoted} AS\nSELECT * FROM (\n{body}\n) WHERE FALSE",
                        location=location,
                    )
                    view.result(timeout=300)
                    created.append({"target": action.target.key, "object_type": "ZERO_ROW_SCHEMA_VIEW", "sql_sha256": action.sql_sha256, "zero_row_guard": True})
                available.add(name)
                action_results.append({"name": name, "target": action.target.key, "action_type": action.action_type, "layer": layer_index, "status": "PASS", "dry_run_total_bytes_processed": total, "sql_sha256": action.sql_sha256})
            except Exception as exc:
                action_results.append({"name": name, "target": action.target.key, "action_type": action.action_type, "layer": layer_index, "status": "FAIL", "sql_sha256": action.sql_sha256, "error": err(exc)})

    assertion_results = []
    required_assertions = [required[name] for name in REQUIRED_ASSERTIONS]
    for action in required_assertions + sorted(generated_assertions, key=lambda value: value.target.key):
        deps = {target_names[d.key] for d in action.dependency_targets if d.key in target_names}
        blocked = sorted(deps - available)
        if blocked:
            assertion_results.append({"name": action.target.name, "target": action.target.key, "status": "BLOCKED_BY_FAILED_DEPENDENCY", "blocked_by": blocked, "sql_sha256": action.sql_sha256})
            continue
        try:
            job = client.query(action.sql[0], job_config=dry, location=location)
            assertion_results.append({"name": action.target.name, "target": action.target.key, "required": action.target.name in REQUIRED_ASSERTIONS, "status": "PASS", "dry_run_total_bytes_processed": int(getattr(job, "total_bytes_processed", 0) or 0), "sql_sha256": action.sql_sha256})
        except Exception as exc:
            assertion_results.append({"name": action.target.name, "target": action.target.key, "required": action.target.name in REQUIRED_ASSERTIONS, "status": "FAIL", "sql_sha256": action.sql_sha256, "error": err(exc)})

    failed_actions = [row for row in action_results if row["status"] != "PASS"]
    failed_assertions = [row for row in assertion_results if row["status"] != "PASS"]
    return {
        **dict(plan),
        "mode": "EXECUTED_SCHEMA_ONLY_VALIDATION",
        "location": location,
        "dataset_labels": labels,
        "created_objects": created,
        "action_results": action_results,
        "assertion_results": assertion_results,
        "failed_action_count": len(failed_actions),
        "failed_assertion_count": len(failed_assertions),
        "status": PASS if not failed_actions and not failed_assertions else "FAIL",
        "validation_dataset_only": True,
        "production_change_allowed": False,
    }


def write_json(document: Mapping[str, Any], output: Path | None):
    text = json.dumps(document, indent=2, sort_keys=True, default=str) + "\n"
    if output is None:
        print(text, end="")
    else:
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
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--expected-plan-checksum")
    parser.add_argument("--acknowledge-validation-write")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.environment != "shadow":
            raise Error("schema check is restricted to environment=shadow")
        git_sha = verify_clean_checkout(args.expected_git_sha)
        rows = load_actions_document(args.actions_json)
        plan, required, generated = build_plan(
            rows,
            project_id=args.project_id,
            operational_dataset=args.operational_dataset,
            validation_dataset=args.validation_dataset,
            compilation_result=args.compilation_result,
            git_sha=git_sha,
            actions_document_sha256=hashlib.sha256(args.actions_json.read_bytes()).hexdigest(),
        )
        result = plan
        if args.execute:
            if args.acknowledge_validation_write != ACK:
                raise Error(f"--execute requires --acknowledge-validation-write {ACK}")
            if not args.expected_plan_checksum:
                raise Error("--execute requires --expected-plan-checksum from a prior plan")
            verify_plan_checksum(plan, args.expected_plan_checksum)
            result = execute_schema_graph(
                plan=plan,
                required=required,
                generated_assertions=generated,
                location=args.location,
            )
        write_json(result, args.output)
        return 0 if result.get("status") != "FAIL" else 2
    except (OSError, Error, subprocess.SubprocessError, ValueError) as exc:
        print(json.dumps({"status": "FAIL", "error": str(exc), "production_change_allowed": False}, sort_keys=True))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

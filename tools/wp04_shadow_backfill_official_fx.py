"""Execute a reviewed WP-04 official-FX plan against shadow tables only."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
from pathlib import Path
from typing import Any, Mapping

from tools import wp04_shadow_backfill as base
from tools.wp04_backfill_core import (
    Wp04BackfillError,
    read_jsonl,
    verify_plan_checksum,
    verify_plan_files,
)
from tools.wp04_fx_source import (
    AVAILABILITY_POLICY,
    POLICY_VERSION,
    PROVIDER,
    SERIES_ID,
    SOURCE_VERSION,
)


ACKNOWLEDGEMENT = "WP04_SHADOW_WRITE"
EXECUTABLE_TABLES = (
    "market_price_raw",
    "corporate_actions_pit",
    "market_session_calendar",
    "fx_rate_raw",
)
FX_RATE_SCHEMA_SPEC = (
    ("fx_rate_revision_id", "STRING", "REQUIRED"),
    ("fx_rate_record_id", "STRING", "REQUIRED"),
    ("ingestion_run_id", "STRING", "REQUIRED"),
    ("provider", "STRING", "REQUIRED"),
    ("series_id", "STRING", "REQUIRED"),
    ("rate_date", "DATE", "REQUIRED"),
    ("source_reference_date", "DATE", "REQUIRED"),
    ("base_currency", "STRING", "REQUIRED"),
    ("quote_currency", "STRING", "REQUIRED"),
    ("rate", "FLOAT64", "REQUIRED"),
    ("status_code", "STRING", "REQUIRED"),
    ("source_record_id", "STRING", "REQUIRED"),
    ("source_version", "STRING", "REQUIRED"),
    ("source_timezone", "STRING", "REQUIRED"),
    ("source_published_at", "TIMESTAMP", "REQUIRED"),
    ("availability_policy", "STRING", "REQUIRED"),
    ("payload_hash", "STRING", "REQUIRED"),
    ("available_at", "TIMESTAMP", "REQUIRED"),
    ("ingested_at", "TIMESTAMP", "REQUIRED"),
    ("quality_status", "STRING", "REQUIRED"),
    ("production_change_allowed", "BOOL", "REQUIRED"),
)


def verify_official_plan(plan: Mapping[str, Any]) -> None:
    policy = plan.get("official_fx_source_policy")
    expected = {
        "policy_version": POLICY_VERSION,
        "provider": PROVIDER,
        "series_id": SERIES_ID,
        "source_version": SOURCE_VERSION,
        "required": True,
        "source_role": "OFFICIAL_SCALAR_RATE",
        "yahoo_fx_role": "DIAGNOSTIC_ONLY",
        "availability_policy": AVAILABILITY_POLICY,
        "production_change_allowed": False,
    }
    if policy != expected:
        raise Wp04BackfillError("plan official_fx_source_policy is missing or invalid")
    versions = plan.get("provider_versions") or {}
    required_versions = {
        "BCCH_BDE": SOURCE_VERSION,
        "OFFICIAL_FX_POLICY": POLICY_VERSION,
        "OFFICIAL_FX_AVAILABILITY_POLICY": AVAILABILITY_POLICY,
    }
    if any(versions.get(key) != value for key, value in required_versions.items()):
        raise Wp04BackfillError("plan official FX provider versions are invalid")
    files = plan.get("files") or {}
    required_files = set(EXECUTABLE_TABLES) | {"official_fx_source_status"}
    missing = sorted(required_files - set(files))
    if missing:
        raise Wp04BackfillError(f"plan is missing official FX files: {missing}")
    market_rows = read_jsonl(Path(files["market_price_raw"]["path"]))
    if any(
        row.get("provider") == PROVIDER
        or (row.get("provider") == "YAHOO" and row.get("ticker") == "CLP=X")
        for row in market_rows
    ):
        raise Wp04BackfillError("market_price_raw contains an eligible or official FX bar")
    fx_rows = read_jsonl(Path(files["fx_rate_raw"]["path"]))
    if not fx_rows:
        raise Wp04BackfillError("fx_rate_raw plan file is empty")
    for row in fx_rows:
        if (
            row.get("provider") != PROVIDER
            or row.get("series_id") != SERIES_ID
            or row.get("availability_policy") != AVAILABILITY_POLICY
            or row.get("production_change_allowed") is not False
        ):
            raise Wp04BackfillError("fx_rate_raw contains an invalid official row")


def execute_plan(
    *,
    plan: Mapping[str, Any],
    project_id: str,
    dataset_id: str,
    location: str,
    client=None,
    bigquery_module=None,
    bq_operations_module=None,
) -> dict[str, Any]:
    if "shadow" not in dataset_id.lower():
        raise Wp04BackfillError("dataset_id must contain shadow")
    verify_plan_files(plan)
    verify_official_plan(plan)
    if bigquery_module is None or bq_operations_module is None:
        bigquery_module, bq_operations_module = base._load_bigquery_modules()
    client = client or bigquery_module.Client(project=project_id, location=location)
    dataset = client.get_dataset(f"{project_id}.{dataset_id}")
    labels = dict(dataset.labels or {})
    if str(dataset.location).lower() != location.lower():
        raise Wp04BackfillError("dataset location mismatch")
    if labels.get("environment") != "shadow" or labels.get("work_package") != "wp04":
        raise Wp04BackfillError(
            "dataset labels must be environment=shadow and work_package=wp04"
        )
    calendar_schema = tuple(
        bigquery_module.SchemaField(name, kind, mode=mode)
        for name, kind, mode in base.CALENDAR_SCHEMA_SPEC
    )
    fx_schema = tuple(
        bigquery_module.SchemaField(name, kind, mode=mode)
        for name, kind, mode in FX_RATE_SCHEMA_SPEC
    )
    specifications = (
        ("market_price_raw", bq_operations_module.PRICE_SCHEMA, "raw_revision_id"),
        ("corporate_actions_pit", bq_operations_module.ACTION_SCHEMA, "action_id"),
        ("market_session_calendar", calendar_schema, "session_id"),
        ("fx_rate_raw", fx_schema, "fx_rate_revision_id"),
    )
    writes = {}
    for table_name, schema, key in specifications:
        destination = f"{project_id}.{dataset_id}.{table_name}"
        if not base.TABLE_ID.fullmatch(destination):
            raise Wp04BackfillError("invalid destination table identifier")
        writes[table_name] = base._append_rows(
            client=client,
            bigquery=bigquery_module,
            destination=destination,
            rows=read_jsonl(Path(plan["files"][table_name]["path"])),
            schema=schema,
            key_field=key,
        )
    return {
        **dict(plan),
        "mode": "EXECUTED_SHADOW_WRITE",
        "project_id": project_id,
        "dataset_id": dataset_id,
        "location": location,
        "dataset_labels": labels,
        "writes": writes,
        "executed_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "production_change_allowed": False,
    }


def _write_output(document: Mapping[str, Any], output: Path | None) -> None:
    text = json.dumps(document, indent=2, sort_keys=True, default=str) + "\n"
    if output is None:
        print(text, end="")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
        print(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-git-sha", required=True)
    parser.add_argument("--execute", action="store_true", required=True)
    parser.add_argument("--plan-file", type=Path, required=True)
    parser.add_argument("--expected-plan-checksum", required=True)
    parser.add_argument("--acknowledge-shadow-write", required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--dataset-id", required=True)
    parser.add_argument("--location", default="us-east1")
    parser.add_argument("--environment", default="shadow")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.environment != "shadow":
            raise Wp04BackfillError("official FX executor is restricted to environment=shadow")
        if args.acknowledge_shadow_write != ACKNOWLEDGEMENT:
            raise Wp04BackfillError(
                f"--execute requires --acknowledge-shadow-write {ACKNOWLEDGEMENT}"
            )
        git_sha = base.verify_clean_checkout(args.expected_git_sha)
        plan = base._load_plan(args.plan_file)
        if plan.get("git_sha") != git_sha:
            raise Wp04BackfillError("plan git_sha does not match checkout")
        verify_plan_checksum(plan, args.expected_plan_checksum)
        result = execute_plan(
            plan=plan,
            project_id=args.project_id,
            dataset_id=args.dataset_id,
            location=args.location,
        )
        _write_output(result, args.output)
        return 0
    except (
        ImportError,
        OSError,
        subprocess.SubprocessError,
        Wp04BackfillError,
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

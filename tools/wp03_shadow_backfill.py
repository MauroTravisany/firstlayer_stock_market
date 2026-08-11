"""Plan or execute a bounded WP-03 SEC filing backfill into the shadow raw table.

The command is read-only by default. BigQuery mutation requires all of:

* ``--execute``;
* ``--environment shadow``;
* ``--acknowledge-shadow-write WP03_SHADOW_WRITE``;
* an explicit bounded ticker list and fiscal-year range.

It never deploys services, changes schedulers, invokes Dataform, or touches broker APIs.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import os
import subprocess
import sys
import types
import uuid
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[1]
CUSTOM_DIR = REPO_ROOT / "cloud-functions" / "financial_data" / "custom_function"
DEFAULT_MAPPING_VERSION = "sec-company-tickers-2026-08-11-v1"
ACKNOWLEDGEMENT = "WP03_SHADOW_WRITE"
MAX_TICKERS_PER_RUN = 10


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=str,
    )


def _sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _load_runtime_modules():
    package_name = "_wp03_financial_runtime"
    package = types.ModuleType(package_name)
    package.__path__ = [str(CUSTOM_DIR)]
    sys.modules[package_name] = package

    loaded = {}
    for module_name in ("point_in_time", "financial_mapping", "sec_source"):
        qualified = f"{package_name}.{module_name}"
        spec = importlib.util.spec_from_file_location(
            qualified, CUSTOM_DIR / f"{module_name}.py"
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(f"Unable to load {module_name}")
        module = importlib.util.module_from_spec(spec)
        sys.modules[qualified] = module
        spec.loader.exec_module(module)
        loaded[module_name] = module
    return loaded


def _git_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def parse_tickers(value: str) -> list[str]:
    tickers = [item.strip().upper() for item in value.replace(";", ",").split(",")]
    tickers = [item for item in tickers if item]
    if not tickers:
        raise ValueError("At least one ticker is required")
    if len(tickers) != len(set(tickers)):
        raise ValueError("Ticker list contains duplicates")
    if len(tickers) > MAX_TICKERS_PER_RUN:
        raise ValueError(
            f"At most {MAX_TICKERS_PER_RUN} tickers are allowed per bounded run"
        )
    return tickers


def _filter_years(rows: Iterable[dict[str, Any]], start_year: int, end_year: int):
    filtered = []
    for row in rows:
        period_end = str(row.get("period_end_date") or "")
        if len(period_end) < 4 or not period_end[:4].isdigit():
            continue
        year = int(period_end[:4])
        if start_year <= year <= end_year:
            filtered.append(row)
    return filtered


def build_backfill_plan(
    *,
    tickers: list[str],
    start_year: int,
    end_year: int,
    expected_mapping_version: str,
    mapping_path: Path | None = None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    if start_year > end_year:
        raise ValueError("start_year cannot be after end_year")
    modules = _load_runtime_modules()
    mapping_module = modules["financial_mapping"]
    sec_source = modules["sec_source"]
    config = {"ticker_cik_map_version": expected_mapping_version}
    if mapping_path is not None:
        config["ticker_cik_map_path"] = str(mapping_path)
    mapping_version, mapping, resolved_mapping_path = mapping_module.ticker_cik_map(
        config
    )
    mapping_hash = hashlib.sha256(resolved_mapping_path.read_bytes()).hexdigest()

    rows: list[dict[str, Any]] = []
    ticker_results = []
    for ticker in tickers:
        entry = mapping.get(ticker)
        if entry is None:
            raise RuntimeError(
                f"Ticker {ticker} is absent from mapping {mapping_version}"
            )
        if entry["financial_reporting"] == "NOT_APPLICABLE":
            ticker_results.append(
                {
                    "ticker": ticker,
                    "status": "NOT_APPLICABLE",
                    "rows": 0,
                    "eligible_rows": 0,
                }
            )
            continue

        submissions = sec_source.fetch_submissions(entry["cik"])
        companyfacts = sec_source.fetch_companyfacts(entry["cik"])
        revisions = sec_source.build_sec_statement_revisions(
            ticker,
            entry["cik"],
            submissions,
            companyfacts,
            reporting_currency=entry["reporting_currency"],
            mapping_version=mapping_version,
        )
        revisions = _filter_years(revisions, start_year, end_year)
        rows.extend(revisions)
        ticker_results.append(
            {
                "ticker": ticker,
                "status": "SEC_EDGAR",
                "reporting_currency": entry["reporting_currency"],
                "rows": len(revisions),
                "eligible_rows": sum(
                    1 for row in revisions if row.get("backtest_eligible")
                ),
            }
        )

    revision_ids = sorted(str(row["revision_id"]) for row in rows)
    reasons = Counter(str(row.get("eligibility_reason")) for row in rows)
    plan = {
        "schema_version": 1,
        "operation": "WP03_SHADOW_SEC_BACKFILL",
        "mode": "PLAN",
        "git_sha": _git_sha(),
        "mapping_version": mapping_version,
        "mapping_sha256": mapping_hash,
        "start_year": start_year,
        "end_year": end_year,
        "tickers": tickers,
        "ticker_results": ticker_results,
        "row_count": len(rows),
        "eligible_row_count": sum(
            1 for row in rows if row.get("backtest_eligible")
        ),
        "eligibility_reasons": dict(sorted(reasons.items())),
        "revision_set_sha256": _sha256(revision_ids),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "production_change_allowed": False,
    }
    return plan, rows


def _load_bigquery_modules():
    try:
        from google.cloud import bigquery
    except ImportError as exc:
        raise RuntimeError(
            "google-cloud-bigquery is required only for --execute"
        ) from exc

    package_name = "_wp03_bigquery_runtime"
    package = types.ModuleType(package_name)
    package.__path__ = [str(CUSTOM_DIR)]
    sys.modules[package_name] = package
    qualified = f"{package_name}.pit_bq_operations"
    spec = importlib.util.spec_from_file_location(
        qualified, CUSTOM_DIR / "pit_bq_operations.py"
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load PIT BigQuery operations")
    module = importlib.util.module_from_spec(spec)
    sys.modules[qualified] = module
    spec.loader.exec_module(module)
    return bigquery, module


def _schema_shape(schema) -> list[tuple[str, str, str]]:
    return [(field.name, field.field_type, field.mode) for field in schema]


def execute_shadow_write(
    *,
    rows: list[dict[str, Any]],
    project_id: str,
    dataset_id: str,
    table_id: str,
    location: str,
) -> dict[str, Any]:
    bigquery, pit_ops = _load_bigquery_modules()
    destination = pit_ops._validated_table_id(
        f"{project_id}.{dataset_id}.{table_id}"
    )
    client = bigquery.Client(project=project_id, location=location)
    destination_table = client.get_table(destination)
    expected_shape = _schema_shape(pit_ops.PIT_STATEMENTS_SCHEMA)
    actual_shape = _schema_shape(destination_table.schema)
    if actual_shape != expected_shape:
        raise RuntimeError(
            "Destination schema mismatch; materialize the exact WP-03 raw table before backfill"
        )
    if not rows:
        return {
            "destination_table": destination,
            "staged_rows": 0,
            "inserted_rows": 0,
        }

    temp_table_id = f"{project_id}.{dataset_id}.{table_id}_backfill_{uuid.uuid4().hex}"
    temp_table = bigquery.Table(temp_table_id, schema=pit_ops.PIT_STATEMENTS_SCHEMA)
    temp_table.expires = datetime.now(timezone.utc) + timedelta(hours=2)
    client.create_table(temp_table)
    try:
        load_config = bigquery.LoadJobConfig(
            schema=pit_ops.PIT_STATEMENTS_SCHEMA,
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        )
        client.load_table_from_json(
            rows, temp_table_id, job_config=load_config
        ).result()
        merge_job = client.query(pit_ops._merge_query(destination, temp_table_id))
        merge_job.result()
        return {
            "destination_table": destination,
            "staged_rows": len(rows),
            "inserted_rows": merge_job.num_dml_affected_rows or 0,
        }
    finally:
        client.delete_table(temp_table_id, not_found_ok=True)


def _write_output(document: dict[str, Any], output: Path | None):
    text = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if output is None:
        print(text, end="")
    else:
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(text, encoding="utf-8")
        print(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", required=True)
    parser.add_argument("--start-year", type=int, required=True)
    parser.add_argument("--end-year", type=int, required=True)
    parser.add_argument(
        "--mapping-version", default=DEFAULT_MAPPING_VERSION
    )
    parser.add_argument("--mapping-path", type=Path)
    parser.add_argument("--environment", default="shadow")
    parser.add_argument("--project-id")
    parser.add_argument("--dataset-id")
    parser.add_argument(
        "--table-id", default="financial_statements_pit_raw"
    )
    parser.add_argument("--location", default="us-east1")
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--acknowledge-shadow-write")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    if args.environment != "shadow":
        raise SystemExit("WP-03 backfill is restricted to environment=shadow")
    if args.table_id != "financial_statements_pit_raw":
        raise SystemExit("WP-03 backfill may only target financial_statements_pit_raw")
    if args.execute:
        if args.acknowledge_shadow_write != ACKNOWLEDGEMENT:
            raise SystemExit(
                f"--execute requires --acknowledge-shadow-write {ACKNOWLEDGEMENT}"
            )
        if not args.project_id or not args.dataset_id:
            raise SystemExit("--execute requires --project-id and --dataset-id")
        if not os.environ.get("SEC_USER_AGENT"):
            raise SystemExit("SEC_USER_AGENT is required for SEC access")

    tickers = parse_tickers(args.tickers)
    plan, rows = build_backfill_plan(
        tickers=tickers,
        start_year=args.start_year,
        end_year=args.end_year,
        expected_mapping_version=args.mapping_version,
        mapping_path=args.mapping_path,
    )
    if args.execute:
        write_result = execute_shadow_write(
            rows=rows,
            project_id=args.project_id,
            dataset_id=args.dataset_id,
            table_id=args.table_id,
            location=args.location,
        )
        plan.update(
            {
                "mode": "EXECUTED_SHADOW_WRITE",
                "write_result": write_result,
                "executed_at": datetime.now(timezone.utc).isoformat(),
            }
        )
    _write_output(plan, args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

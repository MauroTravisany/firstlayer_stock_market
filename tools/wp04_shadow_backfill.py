"""Plan or execute a bounded, append-only WP-04 shadow backfill.

Planning fetches provider data and writes content-addressed JSONL files under a
caller-selected temporary directory. Execution never refetches data: it accepts
only the exact reviewed plan checksum and verifies every file before inserting
unseen revision IDs into the three WP-04 raw shadow tables.
"""

from __future__ import annotations

import argparse
import datetime as dt
import importlib.metadata
import importlib.util
import json
import os
import re
import subprocess
import sys
import types
import uuid
from pathlib import Path
from typing import Any, Mapping, Sequence

from tools.wp04_backfill_core import (
    Wp04BackfillError,
    calendar_rows,
    canonical_json,
    finalize_plan,
    load_asset_set,
    read_jsonl,
    validate_date_ranges,
    validate_max_rows,
    verify_plan_checksum,
    verify_plan_files,
    write_jsonl,
)


ROOT = Path(__file__).resolve().parents[1]
CUSTOM = ROOT / "cloud-functions" / "daily_stocks" / "custom_function"
DEFAULT_ASSET_SET = ROOT / "config" / "wp04_shadow_assets.v1.json"
ACKNOWLEDGEMENT = "WP04_SHADOW_WRITE"
TABLE_ID = re.compile(
    r"^[A-Za-z][A-Za-z0-9-]{4,62}\.[A-Za-z0-9_]+\.[A-Za-z0-9_]+$"
)
CALENDAR_SCHEMA_SPEC = (
    ("session_id", "STRING", "REQUIRED"),
    ("exchange", "STRING", "REQUIRED"),
    ("asset_type", "STRING", "REQUIRED"),
    ("session_date", "DATE", "REQUIRED"),
    ("open_utc", "TIMESTAMP", "REQUIRED"),
    ("close_utc", "TIMESTAMP", "REQUIRED"),
    ("session_status", "STRING", "REQUIRED"),
    ("timezone", "STRING", "REQUIRED"),
    ("expected_15m_bars", "INT64", "REQUIRED"),
    ("expected_1h_bars", "INT64", "REQUIRED"),
    ("calendar_version", "STRING", "REQUIRED"),
    ("calendar_hash", "STRING", "REQUIRED"),
    ("available_at", "TIMESTAMP", "REQUIRED"),
    ("ingested_at", "TIMESTAMP", "REQUIRED"),
)


def _run_git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def verify_clean_checkout(expected_sha: str) -> str:
    expected = str(expected_sha or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", expected):
        raise Wp04BackfillError(
            "expected_git_sha must be a full lowercase commit SHA"
        )
    current = _run_git("rev-parse", "HEAD").lower()
    if current != expected:
        raise Wp04BackfillError(
            f"Git SHA mismatch: expected {expected}, current {current}"
        )
    if _run_git("status", "--porcelain", "--untracked-files=all"):
        raise Wp04BackfillError("WP-04 backfill requires a clean checkout")
    return current


def _load_ingestion_module():
    package_name = "_wp04_daily_runtime"
    package = types.ModuleType(package_name)
    package.__path__ = [str(CUSTOM)]
    sys.modules[package_name] = package
    qualified = f"{package_name}.wp04_ingestion"
    spec = importlib.util.spec_from_file_location(
        qualified,
        CUSTOM / "wp04_ingestion.py",
    )
    if spec is None or spec.loader is None:
        raise Wp04BackfillError("unable to load WP-04 ingestion module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[qualified] = module
    spec.loader.exec_module(module)
    return module


def _load_bigquery_modules():
    try:
        from google.cloud import bigquery
    except ImportError as exc:
        raise Wp04BackfillError(
            "google-cloud-bigquery is required only for --execute"
        ) from exc
    package_name = "_wp04_bq_runtime"
    package = types.ModuleType(package_name)
    package.__path__ = [str(CUSTOM)]
    sys.modules[package_name] = package
    ingestion_name = f"{package_name}.wp04_ingestion"
    ingestion_spec = importlib.util.spec_from_file_location(
        ingestion_name,
        CUSTOM / "wp04_ingestion.py",
    )
    ingestion = importlib.util.module_from_spec(ingestion_spec)
    sys.modules[ingestion_name] = ingestion
    ingestion_spec.loader.exec_module(ingestion)
    bq_name = f"{package_name}.wp04_bq_operations"
    bq_spec = importlib.util.spec_from_file_location(
        bq_name,
        CUSTOM / "wp04_bq_operations.py",
    )
    module = importlib.util.module_from_spec(bq_spec)
    sys.modules[bq_name] = module
    bq_spec.loader.exec_module(module)
    return bigquery, module


def _date(value: str, label: str) -> dt.date:
    try:
        return dt.date.fromisoformat(str(value))
    except ValueError as exc:
        raise Wp04BackfillError(f"{label} must be YYYY-MM-DD") from exc


def _select_assets(
    assets: Sequence[Mapping[str, Any]],
    tickers: str | None,
) -> tuple[dict[str, Any], ...]:
    if not tickers:
        return tuple(dict(row) for row in assets)
    requested = [item.strip().upper() for item in tickers.split(",") if item.strip()]
    if not requested or len(requested) != len(set(requested)):
        raise Wp04BackfillError("tickers must be a unique, non-empty CSV")
    mapping = {row["ticker"]: row for row in assets}
    missing = sorted(set(requested) - set(mapping))
    if missing:
        raise Wp04BackfillError(f"tickers absent from asset set: {missing}")
    return tuple(dict(mapping[ticker]) for ticker in requested)


def _history(
    ticker,
    *,
    start: dt.date,
    end: dt.date,
    interval: str,
    timeout_seconds: int,
):
    frame = ticker.history(
        start=start,
        end=end + dt.timedelta(days=1),
        interval=interval,
        auto_adjust=False,
        actions=True,
        timeout=timeout_seconds,
    )
    if frame is None or frame.empty:
        raise Wp04BackfillError(
            f"Yahoo returned no {interval} rows for {ticker.ticker}"
        )
    return frame


def build_plan(
    *,
    git_sha: str,
    asset_set_path: Path,
    tickers: str | None,
    start_date: dt.date,
    end_date: dt.date,
    intraday_start_date: dt.date,
    hourly_start_date: dt.date,
    max_rows: int,
    work_dir: Path,
    timeout_seconds: int,
) -> dict[str, Any]:
    validate_date_ranges(
        start_date=start_date,
        end_date=end_date,
        intraday_start_date=intraday_start_date,
        hourly_start_date=hourly_start_date,
    )
    max_rows = validate_max_rows(max_rows)
    asset_version, all_assets, asset_sha = load_asset_set(asset_set_path)
    assets = _select_assets(all_assets, tickers)
    ingestion = _load_ingestion_module()
    try:
        import yfinance as yf
    except ImportError as exc:
        raise Wp04BackfillError("yfinance is required for planning") from exc

    generated_at = dt.datetime.now(dt.timezone.utc)
    ingestion_run_id = str(uuid.uuid4())
    provider_versions = {
        "YAHOO": "yfinance-" + importlib.metadata.version("yfinance"),
        "STOOQ": "stooq-csv-v1",
        "CALENDAR": "wp04-market-calendar-v1",
    }
    price_rows: list[dict[str, Any]] = []
    action_rows: list[dict[str, Any]] = []
    asset_results = []
    for asset in assets:
        yahoo = yf.Ticker(asset["yahoo_symbol"])
        before_prices = len(price_rows)
        before_actions = len(action_rows)
        if asset["asset_type"] in {"STOCK", "ETF", "FX"}:
            daily = _history(
                yahoo,
                start=start_date,
                end=end_date,
                interval="1d",
                timeout_seconds=timeout_seconds,
            )
            price_rows.extend(
                ingestion.yfinance_frame_records(
                    daily,
                    provider_symbol=asset["yahoo_symbol"],
                    ticker=asset["ticker"],
                    asset_type=asset["asset_type"],
                    exchange=asset["exchange"],
                    source_interval="1d",
                    currency=asset["currency"],
                    ingestion_run_id=ingestion_run_id,
                    source_version=provider_versions["YAHOO"],
                    ingested_at=generated_at,
                )
            )
            if asset["asset_type"] in {"STOCK", "ETF"}:
                intraday = _history(
                    yahoo,
                    start=intraday_start_date,
                    end=end_date,
                    interval="15m",
                    timeout_seconds=timeout_seconds,
                )
                price_rows.extend(
                    ingestion.yfinance_frame_records(
                        intraday,
                        provider_symbol=asset["yahoo_symbol"],
                        ticker=asset["ticker"],
                        asset_type=asset["asset_type"],
                        exchange=asset["exchange"],
                        source_interval="15m",
                        currency=asset["currency"],
                        ingestion_run_id=ingestion_run_id,
                        source_version=provider_versions["YAHOO"],
                        ingested_at=generated_at,
                    )
                )
                stooq_payloads = ingestion.fetch_stooq_daily(
                    asset["stooq_symbol"],
                    start_date=start_date,
                    end_date=end_date,
                    timeout_seconds=timeout_seconds,
                )
                if not stooq_payloads:
                    raise Wp04BackfillError(
                        f"Stooq returned no daily rows for {asset['ticker']}"
                    )
                for payload in stooq_payloads:
                    price_rows.append(
                        ingestion.normalize_price_record(
                            payload,
                            provider="STOOQ",
                            provider_symbol=asset["stooq_symbol"],
                            ticker=asset["ticker"],
                            asset_type=asset["asset_type"],
                            exchange=asset["exchange"],
                            source_interval="1d",
                            source_timezone="UTC",
                            currency=asset["currency"],
                            ingestion_run_id=ingestion_run_id,
                            source_version=provider_versions["STOOQ"],
                            ingested_at=generated_at,
                        )
                    )
                action_rows.extend(
                    ingestion.normalize_corporate_actions(
                        daily,
                        ticker=asset["ticker"],
                        provider="YAHOO",
                        currency=asset["currency"],
                        ingestion_run_id=ingestion_run_id,
                        source_version=provider_versions["YAHOO"],
                        ingested_at=generated_at,
                    )
                )
        elif asset["asset_type"] == "CRYPTO":
            hourly = _history(
                yahoo,
                start=hourly_start_date,
                end=end_date,
                interval="1h",
                timeout_seconds=timeout_seconds,
            )
            price_rows.extend(
                ingestion.yfinance_frame_records(
                    hourly,
                    provider_symbol=asset["yahoo_symbol"],
                    ticker=asset["ticker"],
                    asset_type="CRYPTO",
                    exchange=asset["exchange"],
                    source_interval="1h",
                    currency=asset["currency"],
                    ingestion_run_id=ingestion_run_id,
                    source_version=provider_versions["YAHOO"],
                    ingested_at=generated_at,
                )
            )
        asset_results.append(
            {
                "ticker": asset["ticker"],
                "asset_type": asset["asset_type"],
                "price_rows": len(price_rows) - before_prices,
                "action_rows": len(action_rows) - before_actions,
            }
        )
        if len(price_rows) + len(action_rows) > max_rows:
            raise Wp04BackfillError(
                "provider rows exceed max_rows; reduce assets or date ranges"
            )

    sessions = calendar_rows(
        assets,
        start_date=start_date,
        end_date=end_date,
        available_at=generated_at,
    )
    if len(price_rows) + len(action_rows) + len(sessions) > max_rows:
        raise Wp04BackfillError(
            "complete plan exceeds max_rows; reduce assets or date ranges"
        )
    for rows, key in (
        (price_rows, "raw_revision_id"),
        (action_rows, "action_id"),
        (sessions, "session_id"),
    ):
        values = [row[key] for row in rows]
        if len(values) != len(set(values)):
            raise Wp04BackfillError(f"duplicate {key} generated during planning")

    work_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "market_price_raw": write_jsonl(
            work_dir / "market_price_raw.jsonl",
            price_rows,
        ),
        "corporate_actions_pit": write_jsonl(
            work_dir / "corporate_actions_pit.jsonl",
            action_rows,
        ),
        "market_session_calendar": write_jsonl(
            work_dir / "market_session_calendar.jsonl",
            sessions,
        ),
    }
    plan = {
        "schema_version": 1,
        "operation": "WP04_SHADOW_BACKFILL",
        "mode": "PLAN",
        "git_sha": git_sha,
        "asset_set_version": asset_version,
        "asset_set_sha256": asset_sha,
        "assets": list(assets),
        "asset_results": asset_results,
        "start_date": start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "intraday_start_date": intraday_start_date.isoformat(),
        "hourly_start_date": hourly_start_date.isoformat(),
        "files": files,
        "total_row_count": sum(row["row_count"] for row in files.values()),
        "max_rows": max_rows,
        "provider_versions": provider_versions,
        "ingestion_run_id": ingestion_run_id,
        "generated_at": generated_at.isoformat(),
        "production_change_allowed": False,
    }
    return finalize_plan(plan)


def _shape(schema) -> list[tuple[str, str, str]]:
    return [(field.name, field.field_type, field.mode) for field in schema]


def _append_rows(
    *,
    client,
    bigquery,
    destination: str,
    rows: list[dict[str, Any]],
    schema,
    key_field: str,
) -> dict[str, Any]:
    table = client.get_table(destination)
    if _shape(table.schema) != _shape(schema):
        raise Wp04BackfillError(
            f"destination schema mismatch for {destination}"
        )
    if not rows:
        return {
            "destination_table": destination,
            "staged_rows": 0,
            "inserted_rows": 0,
        }
    staging = f"{destination}_stage_{uuid.uuid4().hex}"
    temporary = bigquery.Table(staging, schema=list(schema))
    temporary.expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2)
    client.create_table(temporary)
    try:
        load_config = bigquery.LoadJobConfig(
            schema=list(schema),
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        )
        client.load_table_from_json(
            rows,
            staging,
            job_config=load_config,
        ).result()
        columns = [field.name for field in schema]
        query = f"""
MERGE `{destination}` AS T
USING `{staging}` AS S
ON T.`{key_field}` = S.`{key_field}`
WHEN NOT MATCHED THEN
  INSERT ({', '.join(f'`{column}`' for column in columns)})
  VALUES ({', '.join(f'S.`{column}`' for column in columns)})
"""
        job = client.query(query)
        job.result()
        return {
            "destination_table": destination,
            "staged_rows": len(rows),
            "inserted_rows": job.num_dml_affected_rows or 0,
        }
    finally:
        client.delete_table(staging, not_found_ok=True)


def execute_plan(
    *,
    plan: Mapping[str, Any],
    project_id: str,
    dataset_id: str,
    location: str,
) -> dict[str, Any]:
    if "shadow" not in dataset_id.lower():
        raise Wp04BackfillError("dataset_id must contain shadow")
    verify_plan_files(plan)
    bigquery, bq_module = _load_bigquery_modules()
    client = bigquery.Client(project=project_id, location=location)
    dataset = client.get_dataset(f"{project_id}.{dataset_id}")
    labels = dict(dataset.labels or {})
    if str(dataset.location).lower() != location.lower():
        raise Wp04BackfillError("dataset location mismatch")
    if (
        labels.get("environment") != "shadow"
        or labels.get("work_package") != "wp04"
    ):
        raise Wp04BackfillError(
            "dataset labels must be environment=shadow and work_package=wp04"
        )
    calendar_schema = tuple(
        bigquery.SchemaField(name, kind, mode=mode)
        for name, kind, mode in CALENDAR_SCHEMA_SPEC
    )
    specifications = (
        (
            "market_price_raw",
            bq_module.PRICE_SCHEMA,
            "raw_revision_id",
        ),
        (
            "corporate_actions_pit",
            bq_module.ACTION_SCHEMA,
            "action_id",
        ),
        (
            "market_session_calendar",
            calendar_schema,
            "session_id",
        ),
    )
    writes = {}
    for table_name, schema, key in specifications:
        destination = f"{project_id}.{dataset_id}.{table_name}"
        if not TABLE_ID.fullmatch(destination):
            raise Wp04BackfillError("invalid destination table identifier")
        rows = read_jsonl(Path(plan["files"][table_name]["path"]))
        writes[table_name] = _append_rows(
            client=client,
            bigquery=bigquery,
            destination=destination,
            rows=rows,
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


def _load_plan(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Wp04BackfillError(f"invalid plan file {path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("operation") != "WP04_SHADOW_BACKFILL":
        raise Wp04BackfillError("plan file is not a WP-04 backfill plan")
    return value


def _write_output(document: Mapping[str, Any], output: Path | None) -> None:
    text = json.dumps(document, indent=2, sort_keys=True, default=str) + "\n"
    if output is None:
        print(text, end="")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    print(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-git-sha", required=True)
    parser.add_argument("--asset-set", type=Path, default=DEFAULT_ASSET_SET)
    parser.add_argument("--tickers")
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--intraday-start-date")
    parser.add_argument("--hourly-start-date")
    parser.add_argument("--max-rows", type=int, default=250_000)
    parser.add_argument("--work-dir", type=Path)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--plan-file", type=Path)
    parser.add_argument("--expected-plan-checksum")
    parser.add_argument("--acknowledge-shadow-write")
    parser.add_argument("--project-id")
    parser.add_argument("--dataset-id")
    parser.add_argument("--location", default="us-east1")
    parser.add_argument("--environment", default="shadow")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        if args.environment != "shadow":
            raise Wp04BackfillError(
                "WP-04 backfill is restricted to environment=shadow"
            )
        git_sha = verify_clean_checkout(args.expected_git_sha)
        if args.execute:
            if args.acknowledge_shadow_write != ACKNOWLEDGEMENT:
                raise Wp04BackfillError(
                    f"--execute requires --acknowledge-shadow-write {ACKNOWLEDGEMENT}"
                )
            if not args.plan_file or not args.expected_plan_checksum:
                raise Wp04BackfillError(
                    "--execute requires --plan-file and --expected-plan-checksum"
                )
            if not args.project_id or not args.dataset_id:
                raise Wp04BackfillError(
                    "--execute requires --project-id and --dataset-id"
                )
            plan = _load_plan(args.plan_file)
            if plan.get("git_sha") != git_sha:
                raise Wp04BackfillError("plan git_sha does not match checkout")
            verify_plan_checksum(plan, args.expected_plan_checksum)
            result = execute_plan(
                plan=plan,
                project_id=args.project_id,
                dataset_id=args.dataset_id,
                location=args.location,
            )
        else:
            required = {
                "start_date": args.start_date,
                "end_date": args.end_date,
                "intraday_start_date": args.intraday_start_date,
                "hourly_start_date": args.hourly_start_date,
                "work_dir": args.work_dir,
            }
            missing = sorted(key for key, value in required.items() if not value)
            if missing:
                raise Wp04BackfillError(
                    f"planning requires arguments: {missing}"
                )
            result = build_plan(
                git_sha=git_sha,
                asset_set_path=args.asset_set,
                tickers=args.tickers,
                start_date=_date(args.start_date, "start_date"),
                end_date=_date(args.end_date, "end_date"),
                intraday_start_date=_date(
                    args.intraday_start_date,
                    "intraday_start_date",
                ),
                hourly_start_date=_date(
                    args.hourly_start_date,
                    "hourly_start_date",
                ),
                max_rows=args.max_rows,
                work_dir=args.work_dir,
                timeout_seconds=args.timeout_seconds,
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

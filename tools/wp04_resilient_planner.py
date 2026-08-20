"""Resilient WP-04 planner with configurable secondary-source enforcement.

Yahoo remains the mandatory primary source. Stooq is attempted for daily
reconciliation, but an access challenge or provider outage is represented in a
checksum-bound status JSONL instead of aborting optional-secondary validation.
Required-secondary mode continues to fail closed before any BigQuery write.
"""

from __future__ import annotations

import datetime as dt
import importlib.metadata
import uuid
from pathlib import Path
from typing import Any

from tools import wp04_shadow_backfill as base
from tools.wp04_backfill_core import (
    calendar_rows,
    finalize_plan,
    load_asset_set,
    validate_date_ranges,
    validate_max_rows,
    write_jsonl,
)
from tools.wp04_secondary_source import (
    POLICY_VERSION as SECONDARY_SOURCE_POLICY_VERSION,
    SOURCE_VERSION as STOOQ_SOURCE_VERSION,
    SecondarySourceUnavailable,
    fetch_stooq_daily,
    status_document,
)


Wp04BackfillError = base.Wp04BackfillError


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
    require_secondary_source: bool = False,
    stooq_api_key: str | None = None,
) -> dict[str, Any]:
    """Fetch a bounded plan while preserving optional-provider failures."""

    validate_date_ranges(
        start_date=start_date,
        end_date=end_date,
        intraday_start_date=intraday_start_date,
        hourly_start_date=hourly_start_date,
    )
    max_rows = validate_max_rows(max_rows)
    asset_version, all_assets, asset_sha = load_asset_set(asset_set_path)
    assets = base._select_assets(all_assets, tickers)
    ingestion = base._load_ingestion_module()
    try:
        import yfinance as yf
    except ImportError as exc:
        raise Wp04BackfillError("yfinance is required for planning") from exc

    generated_at = dt.datetime.now(dt.timezone.utc)
    ingestion_run_id = str(uuid.uuid4())
    api_key_configured = bool(str(stooq_api_key or "").strip())
    provider_versions = {
        "YAHOO": "yfinance-" + importlib.metadata.version("yfinance"),
        "STOOQ": STOOQ_SOURCE_VERSION,
        "SECONDARY_SOURCE_POLICY": SECONDARY_SOURCE_POLICY_VERSION,
        "SECONDARY_SOURCE_MODE": (
            "REQUIRED" if require_secondary_source else "OPTIONAL"
        ),
        "CALENDAR": "wp04-market-calendar-v1",
    }

    price_rows: list[dict[str, Any]] = []
    action_rows: list[dict[str, Any]] = []
    secondary_status_rows: list[dict[str, Any]] = []
    asset_results: list[dict[str, Any]] = []

    for asset in assets:
        yahoo = yf.Ticker(asset["yahoo_symbol"])
        before_prices = len(price_rows)
        before_actions = len(action_rows)
        secondary_price_rows = 0
        secondary_status = "NOT_APPLICABLE"
        secondary_reason = None

        if asset["asset_type"] in {"STOCK", "ETF", "FX"}:
            daily = base._history(
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
                intraday = base._history(
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

                try:
                    stooq_payloads = fetch_stooq_daily(
                        asset["stooq_symbol"],
                        start_date=start_date,
                        end_date=end_date,
                        timeout_seconds=timeout_seconds,
                        api_key=stooq_api_key,
                    )
                except SecondarySourceUnavailable as exc:
                    secondary_status = "UNAVAILABLE"
                    secondary_reason = exc.reason_code
                    secondary_status_rows.append(
                        status_document(
                            ticker=asset["ticker"],
                            provider_symbol=asset["stooq_symbol"],
                            status=secondary_status,
                            reason_code=secondary_reason,
                            required=require_secondary_source,
                            api_key_configured=api_key_configured,
                            row_count=0,
                            observed_at=generated_at,
                        )
                    )
                    if require_secondary_source:
                        raise Wp04BackfillError(
                            "required secondary source unavailable for "
                            f"{asset['ticker']}: {secondary_reason}"
                        ) from exc
                else:
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
                    secondary_price_rows = len(stooq_payloads)
                    secondary_status = "AVAILABLE"
                    secondary_status_rows.append(
                        status_document(
                            ticker=asset["ticker"],
                            provider_symbol=asset["stooq_symbol"],
                            status=secondary_status,
                            reason_code=None,
                            required=require_secondary_source,
                            api_key_configured=api_key_configured,
                            row_count=secondary_price_rows,
                            observed_at=generated_at,
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
            hourly = base._history(
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
                "secondary_source_status": secondary_status,
                "secondary_source_reason_code": secondary_reason,
                "secondary_price_rows": secondary_price_rows,
            }
        )
        if (
            len(price_rows)
            + len(action_rows)
            + len(secondary_status_rows)
            > max_rows
        ):
            raise Wp04BackfillError(
                "provider rows exceed max_rows; reduce assets or date ranges"
            )

    sessions = calendar_rows(
        assets,
        start_date=start_date,
        end_date=end_date,
        available_at=generated_at,
    )
    if (
        len(price_rows)
        + len(action_rows)
        + len(sessions)
        + len(secondary_status_rows)
        > max_rows
    ):
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
        "secondary_source_status": write_jsonl(
            work_dir / "secondary_source_status.jsonl",
            secondary_status_rows,
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
        "secondary_source_required": bool(require_secondary_source),
        "secondary_source_available_count": sum(
            row["status"] == "AVAILABLE" for row in secondary_status_rows
        ),
        "secondary_source_unavailable_count": sum(
            row["status"] == "UNAVAILABLE" for row in secondary_status_rows
        ),
        "production_change_allowed": False,
    }
    return finalize_plan(plan)

"""Compose the reviewed WP-04 market plan with official BCCh scalar FX rows."""

from __future__ import annotations

import datetime as dt
from pathlib import Path
from typing import Any, Callable

from tools import wp04_quarantine_planner as market
from tools import wp04_shadow_backfill as base
from tools.wp04_backfill_core import (
    Wp04BackfillError,
    calendar_rows,
    finalize_plan,
    load_asset_set,
    read_jsonl,
    validate_date_ranges,
    validate_max_rows,
    write_jsonl,
)
from tools.wp04_fx_source import (
    AVAILABILITY_POLICY,
    POLICY_VERSION,
    PROVIDER,
    SERIES_ID,
    SOURCE_VERSION,
    OfficialFxSourceError,
    fetch_bcch_observed_dollar,
    official_source_policy,
    utc_now,
)


def _selected_assets(asset_set_path: Path, tickers: str | None):
    version, all_assets, checksum = load_asset_set(asset_set_path)
    assets = base._select_assets(all_assets, tickers)
    fx_assets = [row for row in assets if row["primary_source"] == PROVIDER]
    if len(fx_assets) != 1:
        raise Wp04BackfillError("official WP-04 plans require exactly one BCCH_BDE FX asset")
    market_assets = [row for row in assets if row["primary_source"] == "YAHOO"]
    if len(market_assets) != len(assets) - 1:
        raise Wp04BackfillError("official WP-04 plan contains an unsupported primary provider")
    return version, assets, market_assets, fx_assets[0], checksum


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
    bcch_api_token: str | None = None,
    market_planner: Callable[..., dict[str, Any]] = market.build_plan,
    fx_fetcher: Callable[..., tuple[list[dict[str, Any]], dict[str, Any]]] = fetch_bcch_observed_dollar,
    fx_clock: Callable[[], dt.datetime] = utc_now,
) -> dict[str, Any]:
    """Build one checksum-bound plan without putting scalar FX into OHLC rows."""

    validate_date_ranges(
        start_date=start_date,
        end_date=end_date,
        intraday_start_date=intraday_start_date,
        hourly_start_date=hourly_start_date,
    )
    max_rows = validate_max_rows(max_rows)
    asset_version, assets, market_assets, fx_asset, asset_checksum = _selected_assets(
        asset_set_path, tickers
    )
    market_tickers = ",".join(row["ticker"] for row in market_assets)
    plan = market_planner(
        git_sha=git_sha,
        asset_set_path=asset_set_path,
        tickers=market_tickers,
        start_date=start_date,
        end_date=end_date,
        intraday_start_date=intraday_start_date,
        hourly_start_date=hourly_start_date,
        max_rows=max_rows,
        work_dir=work_dir,
        timeout_seconds=timeout_seconds,
        require_secondary_source=require_secondary_source,
        stooq_api_key=stooq_api_key,
        bcch_api_token=None,
    )
    plan_started_at = dt.datetime.fromisoformat(
        str(plan["generated_at"]).replace("Z", "+00:00")
    )
    try:
        fx_rows, fx_status = fx_fetcher(
            token=bcch_api_token,
            start_date=start_date,
            end_date=end_date,
            ingestion_run_id=str(plan["ingestion_run_id"]),
            timeout_seconds=timeout_seconds,
            clock=fx_clock,
        )
    except OfficialFxSourceError as exc:
        raise Wp04BackfillError(
            f"official FX source unavailable: {exc.reason_code}"
        ) from None

    files = dict(plan["files"])
    files.pop("fx_reference_status", None)
    market_sessions = read_jsonl(Path(files["market_session_calendar"]["path"]))
    fx_sessions = calendar_rows(
        [fx_asset],
        start_date=start_date,
        end_date=end_date,
        available_at=plan_started_at,
    )
    sessions = market_sessions + fx_sessions
    session_ids = [row["session_id"] for row in sessions]
    if len(session_ids) != len(set(session_ids)):
        raise Wp04BackfillError("official planner generated duplicate market sessions")
    files["market_session_calendar"] = write_jsonl(
        work_dir / "market_session_calendar.jsonl", sessions
    )
    files["fx_rate_raw"] = write_jsonl(work_dir / "fx_rate_raw.jsonl", fx_rows)
    files["official_fx_source_status"] = write_jsonl(
        work_dir / "official_fx_source_status.jsonl", [fx_status]
    )

    total_row_count = sum(int(metadata["row_count"]) for metadata in files.values())
    if total_row_count > max_rows:
        raise Wp04BackfillError("official WP-04 plan exceeds max_rows")
    provider_versions = dict(plan["provider_versions"])
    provider_versions.pop("FX_REFERENCE_POLICY", None)
    provider_versions.update(
        {
            "BCCH_BDE": SOURCE_VERSION,
            "OFFICIAL_FX_POLICY": POLICY_VERSION,
            "OFFICIAL_FX_AVAILABILITY_POLICY": AVAILABILITY_POLICY,
        }
    )
    official_policy = official_source_policy()
    asset_results = list(plan.get("asset_results") or [])
    asset_results.append(
        {
            "ticker": fx_asset["ticker"],
            "asset_type": "FX",
            "primary_source": PROVIDER,
            "price_rows": 0,
            "action_rows": 0,
            "official_fx_rows": len(fx_rows),
            "yahoo_fx_role": "DIAGNOSTIC_ONLY",
        }
    )
    output = {
        **plan,
        "asset_set_version": asset_version,
        "asset_set_sha256": asset_checksum,
        "assets": list(assets),
        "asset_results": asset_results,
        "files": files,
        "total_row_count": total_row_count,
        "provider_versions": provider_versions,
        "official_fx_source_policy": official_policy,
        "production_change_allowed": False,
    }
    output.pop("fx_reference_policy", None)
    return finalize_plan(output)

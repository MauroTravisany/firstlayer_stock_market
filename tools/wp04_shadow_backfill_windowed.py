"""Create a WP-04 backfill plan using current safe provider windows."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any, Callable, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import wp04_shadow_backfill as backfill
from tools.wp04_provider_window import (
    DEFAULT_DAILY_START_DATE,
    DEFAULT_END_LAG_DAYS,
    DEFAULT_HOURLY_LOOKBACK_DAYS,
    DEFAULT_INTRADAY_LOOKBACK_DAYS,
    ProviderWindowError,
    resolve_provider_window,
    write_document,
)


def _date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must be YYYY-MM-DD") from exc


def build_windowed_plan(
    *,
    git_sha: str,
    asset_set_path: Path,
    tickers: str | None,
    daily_start_date: dt.date,
    end_lag_days: int,
    intraday_lookback_days: int,
    hourly_lookback_days: int,
    max_rows: int,
    work_dir: Path,
    timeout_seconds: int,
    anchor_at: dt.datetime | None = None,
    planner: Callable[..., dict[str, Any]] = backfill.build_plan,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Resolve safe dates, then invoke the reviewed bounded planner."""

    window = resolve_provider_window(
        anchor_at=anchor_at,
        daily_start_date=daily_start_date,
        end_lag_days=end_lag_days,
        intraday_lookback_days=intraday_lookback_days,
        hourly_lookback_days=hourly_lookback_days,
    )
    plan = planner(
        git_sha=git_sha,
        asset_set_path=asset_set_path,
        tickers=tickers,
        start_date=dt.date.fromisoformat(window["start_date"]),
        end_date=dt.date.fromisoformat(window["end_date"]),
        intraday_start_date=dt.date.fromisoformat(
            window["intraday_start_date"]
        ),
        hourly_start_date=dt.date.fromisoformat(window["hourly_start_date"]),
        max_rows=max_rows,
        work_dir=work_dir,
        timeout_seconds=timeout_seconds,
    )
    result = {
        **plan,
        "provider_window_policy": window,
        "provider_window_checksum": window["window_checksum"],
    }
    return result, window


def _write_plan(document: Mapping[str, Any], output: Path | None) -> None:
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
    parser.add_argument(
        "--asset-set",
        type=Path,
        default=backfill.DEFAULT_ASSET_SET,
    )
    parser.add_argument("--tickers")
    parser.add_argument(
        "--daily-start-date",
        type=_date,
        default=DEFAULT_DAILY_START_DATE,
    )
    parser.add_argument("--end-lag-days", type=int, default=DEFAULT_END_LAG_DAYS)
    parser.add_argument(
        "--intraday-lookback-days",
        type=int,
        default=DEFAULT_INTRADAY_LOOKBACK_DAYS,
    )
    parser.add_argument(
        "--hourly-lookback-days",
        type=int,
        default=DEFAULT_HOURLY_LOOKBACK_DAYS,
    )
    parser.add_argument("--max-rows", type=int, default=100_000)
    parser.add_argument("--work-dir", type=Path, required=True)
    parser.add_argument("--timeout-seconds", type=int, default=30)
    parser.add_argument("--window-output", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        git_sha = backfill.verify_clean_checkout(args.expected_git_sha)
        plan, window = build_windowed_plan(
            git_sha=git_sha,
            asset_set_path=args.asset_set,
            tickers=args.tickers,
            daily_start_date=args.daily_start_date,
            end_lag_days=args.end_lag_days,
            intraday_lookback_days=args.intraday_lookback_days,
            hourly_lookback_days=args.hourly_lookback_days,
            max_rows=args.max_rows,
            work_dir=args.work_dir,
            timeout_seconds=args.timeout_seconds,
        )
        write_document(window, args.window_output)
        _write_plan(plan, args.output)
        return 0
    except (
        ImportError,
        OSError,
        ProviderWindowError,
        backfill.Wp04BackfillError,
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
"""Resolve safe moving provider windows for WP-04.

Yahoo evaluates intraday retention against the provider's current clock, not
against the requested backfill end date. This module produces deterministic,
checksummed effective dates with conservative safety buffers.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


POLICY_VERSION = "wp04-yahoo-moving-window-v1"
INTRADAY_RETENTION_DAYS = 60
INTRADAY_SAFETY_BUFFER_DAYS = 2
INTRADAY_SAFE_LOOKBACK_DAYS = (
    INTRADAY_RETENTION_DAYS - INTRADAY_SAFETY_BUFFER_DAYS
)
HOURLY_RETENTION_DAYS = 730
HOURLY_SAFETY_BUFFER_DAYS = 2
HOURLY_SAFE_LOOKBACK_DAYS = (
    HOURLY_RETENTION_DAYS - HOURLY_SAFETY_BUFFER_DAYS
)
DEFAULT_DAILY_START_DATE = dt.date(2024, 1, 1)
DEFAULT_END_LAG_DAYS = 2
DEFAULT_INTRADAY_LOOKBACK_DAYS = 45
DEFAULT_HOURLY_LOOKBACK_DAYS = 365


class ProviderWindowError(ValueError):
    """A requested provider window is unsafe or internally inconsistent."""


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )


def _sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _aware_utc(value: dt.datetime | None = None) -> dt.datetime:
    if value is None:
        return dt.datetime.now(dt.timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ProviderWindowError("anchor_at must be timezone-aware")
    return value.astimezone(dt.timezone.utc)


def resolve_provider_window(
    *,
    anchor_at: dt.datetime | None = None,
    daily_start_date: dt.date = DEFAULT_DAILY_START_DATE,
    end_lag_days: int = DEFAULT_END_LAG_DAYS,
    intraday_lookback_days: int = DEFAULT_INTRADAY_LOOKBACK_DAYS,
    hourly_lookback_days: int = DEFAULT_HOURLY_LOOKBACK_DAYS,
) -> dict[str, Any]:
    """Return current, safe dates for Yahoo daily, 15m and 1h requests."""

    anchor_utc = _aware_utc(anchor_at)
    if end_lag_days < 1:
        raise ProviderWindowError("end_lag_days must be at least one")
    if not 1 <= intraday_lookback_days <= INTRADAY_SAFE_LOOKBACK_DAYS:
        raise ProviderWindowError(
            "intraday_lookback_days exceeds the safe Yahoo 15m window"
        )
    if not 1 <= hourly_lookback_days <= HOURLY_SAFE_LOOKBACK_DAYS:
        raise ProviderWindowError(
            "hourly_lookback_days exceeds the safe Yahoo 1h window"
        )

    anchor_date = anchor_utc.date()
    end_date = anchor_date - dt.timedelta(days=end_lag_days)
    intraday_start = end_date - dt.timedelta(days=intraday_lookback_days)
    hourly_start = end_date - dt.timedelta(days=hourly_lookback_days)
    if daily_start_date > intraday_start or daily_start_date > hourly_start:
        raise ProviderWindowError(
            "daily_start_date must not be later than provider-specific starts"
        )

    intraday_earliest = anchor_date - dt.timedelta(
        days=INTRADAY_SAFE_LOOKBACK_DAYS
    )
    hourly_earliest = anchor_date - dt.timedelta(
        days=HOURLY_SAFE_LOOKBACK_DAYS
    )
    if intraday_start < intraday_earliest:
        raise ProviderWindowError(
            "resolved 15m start is outside the safe moving window"
        )
    if hourly_start < hourly_earliest:
        raise ProviderWindowError(
            "resolved 1h start is outside the safe moving window"
        )

    stable = {
        "schema_version": 1,
        "operation": "WP04_PROVIDER_WINDOW_RESOLUTION",
        "policy_version": POLICY_VERSION,
        "anchor_at_utc": anchor_utc.isoformat(),
        "provider_anchor_date": anchor_date.isoformat(),
        "start_date": daily_start_date.isoformat(),
        "end_date": end_date.isoformat(),
        "intraday_start_date": intraday_start.isoformat(),
        "hourly_start_date": hourly_start.isoformat(),
        "end_lag_days": end_lag_days,
        "intraday": {
            "interval": "15m",
            "retention_days": INTRADAY_RETENTION_DAYS,
            "safety_buffer_days": INTRADAY_SAFETY_BUFFER_DAYS,
            "lookback_days": intraday_lookback_days,
            "earliest_safe_start_date": intraday_earliest.isoformat(),
            "within_provider_window": True,
        },
        "hourly": {
            "interval": "1h",
            "retention_days": HOURLY_RETENTION_DAYS,
            "safety_buffer_days": HOURLY_SAFETY_BUFFER_DAYS,
            "lookback_days": hourly_lookback_days,
            "earliest_safe_start_date": hourly_earliest.isoformat(),
            "within_provider_window": True,
        },
        "production_change_allowed": False,
    }
    return {**stable, "window_checksum": _sha256(stable)}


def _date(value: str) -> dt.date:
    try:
        return dt.date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("date must be YYYY-MM-DD") from exc


def write_document(document: Mapping[str, Any], output: Path | None) -> None:
    text = json.dumps(document, indent=2, sort_keys=True) + "\n"
    if output is None:
        print(text, end="")
        return
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")
    print(output)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
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
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        document = resolve_provider_window(
            daily_start_date=args.daily_start_date,
            end_lag_days=args.end_lag_days,
            intraday_lookback_days=args.intraday_lookback_days,
            hourly_lookback_days=args.hourly_lookback_days,
        )
        write_document(document, args.output)
        return 0
    except (OSError, ProviderWindowError, ValueError) as exc:
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
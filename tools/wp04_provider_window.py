"""Resolve and verify safe moving provider windows for WP-04.

Yahoo evaluates intraday retention against the provider's current clock, not
against a historical backfill end date. This module resolves a current bounded
window, records the UTC anchor and produces a deterministic checksum that is
bound into the WP-04 backfill plan.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


POLICY_VERSION = "wp04-yahoo-provider-window-v1"
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
SHA256 = re.compile(r"^[0-9a-f]{64}$")


class ProviderWindowError(ValueError):
    """A requested provider window is unsafe or internally inconsistent."""


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _sha256(value: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _aware_utc(value: dt.datetime | None = None) -> dt.datetime:
    if value is None:
        return dt.datetime.now(dt.timezone.utc)
    if value.tzinfo is None or value.utcoffset() is None:
        raise ProviderWindowError("anchor_at must be timezone-aware")
    return value.astimezone(dt.timezone.utc)


def _date(document: Mapping[str, Any], key: str) -> dt.date:
    try:
        return dt.date.fromisoformat(str(document[key]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ProviderWindowError(f"{key} must be an ISO date") from exc


def _datetime(document: Mapping[str, Any], key: str) -> dt.datetime:
    try:
        value = str(document[key]).replace("Z", "+00:00")
        parsed = dt.datetime.fromisoformat(value)
    except (KeyError, TypeError, ValueError) as exc:
        raise ProviderWindowError(f"{key} must be an ISO datetime") from exc
    return _aware_utc(parsed)


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
    if intraday_start > end_date or hourly_start > end_date:
        raise ProviderWindowError("provider window does not overlap end_date")

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
            "safe_lookback_days": INTRADAY_SAFE_LOOKBACK_DAYS,
            "lookback_days": intraday_lookback_days,
            "earliest_safe_start_date": intraday_earliest.isoformat(),
            "within_provider_window": True,
        },
        "hourly": {
            "interval": "1h",
            "retention_days": HOURLY_RETENTION_DAYS,
            "safety_buffer_days": HOURLY_SAFETY_BUFFER_DAYS,
            "safe_lookback_days": HOURLY_SAFE_LOOKBACK_DAYS,
            "lookback_days": hourly_lookback_days,
            "earliest_safe_start_date": hourly_earliest.isoformat(),
            "within_provider_window": True,
        },
        "production_change_allowed": False,
    }
    result = {**stable, "window_checksum": _sha256(stable)}
    verify_provider_window(result)
    return result


def verify_provider_window(document: Mapping[str, Any]) -> str:
    """Fail closed unless a provider-window document is complete and untampered."""

    if not isinstance(document, Mapping):
        raise ProviderWindowError("provider window must be an object")
    stable = dict(document)
    checksum = str(stable.pop("window_checksum", "")).lower()
    if not SHA256.fullmatch(checksum):
        raise ProviderWindowError("window_checksum must be SHA-256")
    if stable.get("operation") != "WP04_PROVIDER_WINDOW_RESOLUTION":
        raise ProviderWindowError("provider window operation is invalid")
    if stable.get("policy_version") != POLICY_VERSION:
        raise ProviderWindowError("provider window policy version is invalid")
    if stable.get("production_change_allowed") is not False:
        raise ProviderWindowError("provider window cannot allow production changes")
    actual = _sha256(stable)
    if actual != checksum:
        raise ProviderWindowError(
            f"provider window checksum mismatch: expected {checksum}, actual {actual}"
        )

    anchor_at = _datetime(stable, "anchor_at_utc")
    anchor_date = _date(stable, "provider_anchor_date")
    start_date = _date(stable, "start_date")
    end_date = _date(stable, "end_date")
    intraday_start = _date(stable, "intraday_start_date")
    hourly_start = _date(stable, "hourly_start_date")
    if anchor_at.date() != anchor_date:
        raise ProviderWindowError("provider anchor date does not match anchor_at")
    if not start_date <= intraday_start <= end_date:
        raise ProviderWindowError("15m window is outside the daily scope")
    if not start_date <= hourly_start <= end_date:
        raise ProviderWindowError("1h window is outside the daily scope")

    intraday = stable.get("intraday")
    hourly = stable.get("hourly")
    if not isinstance(intraday, Mapping) or not isinstance(hourly, Mapping):
        raise ProviderWindowError("provider interval policies are missing")
    expected_intraday = {
        "interval": "15m",
        "retention_days": INTRADAY_RETENTION_DAYS,
        "safety_buffer_days": INTRADAY_SAFETY_BUFFER_DAYS,
        "safe_lookback_days": INTRADAY_SAFE_LOOKBACK_DAYS,
        "earliest_safe_start_date": (
            anchor_date - dt.timedelta(days=INTRADAY_SAFE_LOOKBACK_DAYS)
        ).isoformat(),
        "within_provider_window": True,
    }
    expected_hourly = {
        "interval": "1h",
        "retention_days": HOURLY_RETENTION_DAYS,
        "safety_buffer_days": HOURLY_SAFETY_BUFFER_DAYS,
        "safe_lookback_days": HOURLY_SAFE_LOOKBACK_DAYS,
        "earliest_safe_start_date": (
            anchor_date - dt.timedelta(days=HOURLY_SAFE_LOOKBACK_DAYS)
        ).isoformat(),
        "within_provider_window": True,
    }
    for key, value in expected_intraday.items():
        if intraday.get(key) != value:
            raise ProviderWindowError(f"invalid 15m provider policy field {key}")
    for key, value in expected_hourly.items():
        if hourly.get(key) != value:
            raise ProviderWindowError(f"invalid 1h provider policy field {key}")
    try:
        intraday_lookback = int(intraday["lookback_days"])
        hourly_lookback = int(hourly["lookback_days"])
        end_lag_days = int(stable["end_lag_days"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ProviderWindowError("provider lookback metadata is invalid") from exc
    if not 1 <= intraday_lookback <= INTRADAY_SAFE_LOOKBACK_DAYS:
        raise ProviderWindowError("15m lookback exceeds safe provider policy")
    if not 1 <= hourly_lookback <= HOURLY_SAFE_LOOKBACK_DAYS:
        raise ProviderWindowError("1h lookback exceeds safe provider policy")
    if end_lag_days < 1 or end_date != anchor_date - dt.timedelta(days=end_lag_days):
        raise ProviderWindowError("provider end-date lag is invalid")
    if intraday_start != end_date - dt.timedelta(days=intraday_lookback):
        raise ProviderWindowError("15m start does not match declared lookback")
    if hourly_start != end_date - dt.timedelta(days=hourly_lookback):
        raise ProviderWindowError("1h start does not match declared lookback")
    return checksum


def _cli_date(value: str) -> dt.date:
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
        type=_cli_date,
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

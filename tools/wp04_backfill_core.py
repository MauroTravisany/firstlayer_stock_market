"""Compatibility facade for WP-04 bounded-backfill planning helpers.

The reviewed implementation is retained in :mod:`tools.wp04_backfill_core_impl`.
This facade corrects the market-calendar expectation contract without changing
plan identity, JSONL hashing, append-only semantics, or provider scope.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Mapping, Sequence

from tools import wp04_backfill_core_impl as _core


ASSET_TYPES = _core.ASSET_TYPES
ASSET_SET_VERSION = _core.ASSET_SET_VERSION
MAX_ASSETS = _core.MAX_ASSETS
MAX_DAILY_DAYS = _core.MAX_DAILY_DAYS
MAX_INTRADAY_DAYS = _core.MAX_INTRADAY_DAYS
MAX_HOURLY_DAYS = _core.MAX_HOURLY_DAYS
MAX_ROWS_HARD_LIMIT = _core.MAX_ROWS_HARD_LIMIT
Wp04BackfillError = _core.Wp04BackfillError

canonical_json = _core.canonical_json
sha256_bytes = _core.sha256_bytes
load_asset_set = _core.load_asset_set
validate_date_ranges = _core.validate_date_ranges
validate_max_rows = _core.validate_max_rows
write_jsonl = _core.write_jsonl
read_jsonl = _core.read_jsonl
plan_identity = _core.plan_identity
finalize_plan = _core.finalize_plan
verify_plan_files = _core.verify_plan_files
verify_plan_checksum = _core.verify_plan_checksum


def calendar_rows(
    assets: Sequence[Mapping[str, Any]],
    *,
    start_date: dt.date,
    end_date: dt.date,
    available_at: dt.datetime,
    calendar_version: str = "wp04-market-calendar-v1",
) -> list[dict[str, Any]]:
    """Build deterministic sessions with interval expectations by market.

    XNYS regular sessions are 6.5 hours (and early closes are 3.5 hours), so a
    one-hour bar count is not an exact partition of the session. WP-04 consumes
    15-minute equity bars and records ``expected_1h_bars=0`` for XNYS rather
    than fabricating a fractional or rounded expectation. FX and crypto retain
    exact one-hour expectations.
    """

    if available_at.tzinfo is None or available_at.utcoffset() is None:
        raise Wp04BackfillError("calendar available_at must be timezone-aware")

    pairs = sorted({(row["exchange"], row["asset_type"]) for row in assets})
    output: list[dict[str, Any]] = []
    for exchange, asset_type in pairs:
        for session in _core.iter_sessions(
            start_date,
            end_date,
            exchange=exchange,
            asset_type=asset_type,
        ):
            expected_1h_bars = (
                0
                if session.exchange == "XNYS"
                else _core.expected_bars(session, "1h")
            )
            base = {
                "exchange": session.exchange,
                "asset_type": session.asset_type,
                "session_date": session.session_date,
                "open_utc": session.open_utc,
                "close_utc": session.close_utc,
                "session_status": session.session_status,
                "timezone": session.timezone,
                "expected_15m_bars": _core.expected_bars(session, "15m"),
                "expected_1h_bars": expected_1h_bars,
                "calendar_version": calendar_version,
            }
            calendar_hash = _core.sha256_json(base)
            output.append(
                {
                    "session_id": "session_"
                    + _core.sha256_json(
                        {
                            "exchange": session.exchange,
                            "asset_type": session.asset_type,
                            "session_date": session.session_date,
                            "calendar_hash": calendar_hash,
                        }
                    ),
                    **base,
                    "calendar_hash": calendar_hash,
                    "available_at": available_at,
                    "ingested_at": available_at,
                }
            )
    return output


def __getattr__(name: str) -> Any:
    try:
        return getattr(_core, name)
    except AttributeError as exc:
        raise AttributeError(name) from exc


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_core)))

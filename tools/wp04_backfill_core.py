"""Compatibility facade for WP-04 bounded-backfill planning helpers.

The reviewed implementation is retained in :mod:`tools.wp04_backfill_core_impl`.
This facade corrects market-calendar expectations and binds every provider,
quality, and moving-window policy into the executable plan checksum.
"""

from __future__ import annotations

import datetime as dt
import re
from typing import Any, Mapping, Sequence

from tools import wp04_backfill_core_impl as _core
from tools.wp04_provider_window import verify_provider_window

ASSET_TYPES = _core.ASSET_TYPES
PRIMARY_SOURCES = _core.PRIMARY_SOURCES
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
verify_plan_files = _core.verify_plan_files

def _provider_window_identity(plan: Mapping[str, Any], *, required: bool) -> dict[str, Any]:
    policy = plan.get("provider_window_policy")
    checksum = plan.get("provider_window_checksum")
    if policy is None and checksum is None:
        if required:
            raise Wp04BackfillError("plan is missing checksum-bound provider_window_policy")
        return {}
    if not isinstance(policy, Mapping):
        raise Wp04BackfillError("provider_window_policy must be an object")
    try:
        verified = verify_provider_window(policy)
    except ValueError as exc:
        raise Wp04BackfillError(str(exc)) from exc
    if str(checksum or "").lower() != verified:
        raise Wp04BackfillError("provider_window_checksum mismatch")
    return {"provider_window_policy": dict(policy), "provider_window_checksum": verified}

def _optional_policy_identity(plan: Mapping[str, Any], name: str) -> dict[str, Any]:
    value = plan.get(name)
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise Wp04BackfillError(f"{name} must be an object")
    return {name: dict(value)}

def plan_identity(plan: Mapping[str, Any]) -> dict[str, Any]:
    result = {**_core.plan_identity(plan), **_provider_window_identity(plan, required=False), **_optional_policy_identity(plan, "primary_source_policy"), **_optional_policy_identity(plan, "fx_reference_policy")}
    for key in ("secondary_source_required", "secondary_source_available_count", "secondary_source_unavailable_count"):
        if key in plan:
            result[key] = plan[key]
    return result

def finalize_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(plan)
    result["plan_checksum"] = _core.sha256_json(plan_identity(result))
    return result

def verify_plan_checksum(plan: Mapping[str, Any], expected: str) -> str:
    expected = str(expected or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise Wp04BackfillError("expected_plan_checksum must be SHA-256")
    _provider_window_identity(plan, required=True)
    actual = _core.sha256_json(plan_identity(plan))
    if actual != expected or str(plan.get("plan_checksum")) != expected:
        raise Wp04BackfillError(f"plan checksum mismatch: expected {expected}, actual {actual}")
    return actual

def calendar_rows(assets: Sequence[Mapping[str, Any]], *, start_date: dt.date, end_date: dt.date, available_at: dt.datetime, calendar_version: str = "wp04-market-calendar-v1") -> list[dict[str, Any]]:
    if available_at.tzinfo is None or available_at.utcoffset() is None:
        raise Wp04BackfillError("calendar available_at must be timezone-aware")
    output: list[dict[str, Any]] = []
    for exchange, asset_type in sorted({(row["exchange"], row["asset_type"]) for row in assets}):
        for session in _core.iter_sessions(start_date, end_date, exchange=exchange, asset_type=asset_type):
            expected_1h_bars = 0 if session.exchange == "XNYS" else _core.expected_bars(session, "1h")
            base = {"exchange": session.exchange, "asset_type": session.asset_type, "session_date": session.session_date, "open_utc": session.open_utc, "close_utc": session.close_utc, "session_status": session.session_status, "timezone": session.timezone, "expected_15m_bars": _core.expected_bars(session, "15m"), "expected_1h_bars": expected_1h_bars, "calendar_version": calendar_version}
            calendar_hash = _core.sha256_json(base)
            output.append({"session_id": "session_" + _core.sha256_json({"exchange": session.exchange, "asset_type": session.asset_type, "session_date": session.session_date, "calendar_hash": calendar_hash}), **base, "calendar_hash": calendar_hash, "available_at": available_at, "ingested_at": available_at})
    return output

def __getattr__(name: str) -> Any:
    try:
        return getattr(_core, name)
    except AttributeError as exc:
        raise AttributeError(name) from exc

def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_core)))

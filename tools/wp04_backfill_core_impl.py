"""Pure planning helpers for the bounded WP-04 shadow backfill."""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from packages.common.hashing import sha256_json
from packages.market_data.calendar import expected_bars, iter_sessions

ASSET_TYPES = {"STOCK", "ETF", "CRYPTO", "FX"}
PRIMARY_SOURCES = {"YAHOO", "BCCH_BDE"}
ASSET_SET_VERSION = re.compile(r"^[A-Za-z0-9._-]+$")
MAX_ASSETS = 20
MAX_DAILY_DAYS = 3660
MAX_INTRADAY_DAYS = 60
MAX_HOURLY_DAYS = 730
MAX_ROWS_HARD_LIMIT = 500_000

class Wp04BackfillError(ValueError):
    """A bounded WP-04 plan is invalid or not reproducible."""

def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=_json_default, allow_nan=False)

def _json_default(value: Any):
    if isinstance(value, dt.datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise Wp04BackfillError("datetime values must be timezone-aware")
        return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, dt.date):
        return value.isoformat()
    raise TypeError(type(value).__name__)

def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()

def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None

def load_asset_set(path: Path) -> tuple[str, tuple[dict[str, Any], ...], str]:
    try:
        raw = path.read_bytes()
        document = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise Wp04BackfillError(f"invalid asset set {path}: {exc}") from exc
    if not isinstance(document, Mapping):
        raise Wp04BackfillError("asset set root must be an object")
    version = str(document.get("asset_set_version") or "").strip()
    if not ASSET_SET_VERSION.fullmatch(version):
        raise Wp04BackfillError("asset_set_version is invalid")
    rows = document.get("assets")
    if not isinstance(rows, list) or not rows or len(rows) > MAX_ASSETS:
        raise Wp04BackfillError(f"asset set must contain between 1 and {MAX_ASSETS} rows")
    normalized = []
    tickers = set()
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise Wp04BackfillError(f"asset row {index} must be an object")
        ticker = str(row.get("ticker") or "").strip().upper()
        asset_type = str(row.get("asset_type") or "").strip().upper()
        exchange = str(row.get("exchange") or "").strip().upper()
        currency = str(row.get("currency") or "").strip().upper()
        primary_provider = str(
            row.get("primary_provider") or row.get("primary_source") or "YAHOO"
        ).strip().upper()
        primary_source = str(
            row.get("primary_source") or primary_provider
        ).strip().upper()
        if primary_provider != primary_source:
            raise Wp04BackfillError(
                f"asset row {index} has mismatched primary provider aliases"
            )
        yahoo_symbol = _optional_text(row.get("yahoo_symbol"))
        yahoo_role = str(row.get("yahoo_role") or "PRIMARY").strip().upper()
        stooq_symbol = _optional_text(row.get("stooq_symbol"))
        if stooq_symbol is not None:
            stooq_symbol = stooq_symbol.lower()
        bcch_series_id = _optional_text(row.get("bcch_series_id"))
        if not ticker or ticker in tickers:
            raise Wp04BackfillError(f"asset row {index} has missing or duplicate ticker")
        if asset_type not in ASSET_TYPES:
            raise Wp04BackfillError(f"asset row {index} has unsupported asset_type")
        if primary_source not in PRIMARY_SOURCES:
            raise Wp04BackfillError(f"asset row {index} has unsupported primary_source")
        if not exchange or not currency:
            raise Wp04BackfillError(f"asset row {index} is incomplete")
        if primary_source == "YAHOO":
            if not yahoo_symbol or yahoo_role != "PRIMARY":
                raise Wp04BackfillError(f"asset row {index} requires yahoo_symbol")
            if bcch_series_id:
                raise Wp04BackfillError(f"asset row {index} cannot mix Yahoo and BCCH fields")
        elif (
            asset_type != "FX"
            or exchange != "FX_24_5"
            or currency != "CLP"
            or yahoo_symbol != "CLP=X"
            or yahoo_role != "DIAGNOSTIC_ONLY"
            or bcch_series_id != "F073.TCO.PRE.Z.D"
        ):
            raise Wp04BackfillError(f"asset row {index} has invalid BCCH_BDE FX configuration")
        if asset_type in {"STOCK", "ETF"} and not stooq_symbol:
            raise Wp04BackfillError(f"asset row {index} requires stooq_symbol for source reconciliation")
        if asset_type not in {"STOCK", "ETF"} and stooq_symbol:
            raise Wp04BackfillError(f"asset row {index} must not configure Stooq for {asset_type}")
        tickers.add(ticker)
        normalized.append({"ticker": ticker, "asset_type": asset_type, "exchange": exchange, "currency": currency, "primary_provider": primary_provider, "primary_source": primary_source, "yahoo_symbol": yahoo_symbol, "yahoo_role": yahoo_role, "stooq_symbol": stooq_symbol, "bcch_series_id": bcch_series_id})
    return version, tuple(normalized), sha256_bytes(raw)

def validate_date_ranges(*, start_date: dt.date, end_date: dt.date, intraday_start_date: dt.date, hourly_start_date: dt.date) -> None:
    if end_date < start_date:
        raise Wp04BackfillError("end_date cannot precede start_date")
    if intraday_start_date < start_date or intraday_start_date > end_date:
        raise Wp04BackfillError("intraday_start_date must be inside the daily range")
    if hourly_start_date < start_date or hourly_start_date > end_date:
        raise Wp04BackfillError("hourly_start_date must be inside the daily range")
    if (end_date - start_date).days + 1 > MAX_DAILY_DAYS:
        raise Wp04BackfillError("daily range exceeds hard limit")
    if (end_date - intraday_start_date).days + 1 > MAX_INTRADAY_DAYS:
        raise Wp04BackfillError("intraday range exceeds Yahoo hard limit")
    if (end_date - hourly_start_date).days + 1 > MAX_HOURLY_DAYS:
        raise Wp04BackfillError("hourly range exceeds Yahoo hard limit")

def validate_max_rows(value: int) -> int:
    value = int(value)
    if value <= 0 or value > MAX_ROWS_HARD_LIMIT:
        raise Wp04BackfillError(f"max_rows must be between 1 and {MAX_ROWS_HARD_LIMIT}")
    return value

def calendar_rows(assets: Sequence[Mapping[str, Any]], *, start_date: dt.date, end_date: dt.date, available_at: dt.datetime, calendar_version: str = "wp04-market-calendar-v1") -> list[dict[str, Any]]:
    if available_at.tzinfo is None or available_at.utcoffset() is None:
        raise Wp04BackfillError("calendar available_at must be timezone-aware")
    output = []
    for exchange, asset_type in sorted({(row["exchange"], row["asset_type"]) for row in assets}):
        for session in iter_sessions(start_date, end_date, exchange=exchange, asset_type=asset_type):
            base = {"exchange": session.exchange, "asset_type": session.asset_type, "session_date": session.session_date, "open_utc": session.open_utc, "close_utc": session.close_utc, "session_status": session.session_status, "timezone": session.timezone, "expected_15m_bars": expected_bars(session, "15m"), "expected_1h_bars": expected_bars(session, "1h"), "calendar_version": calendar_version}
            calendar_hash = sha256_json(base)
            output.append({"session_id": "session_" + sha256_json({"exchange": session.exchange, "asset_type": session.asset_type, "session_date": session.session_date, "calendar_hash": calendar_hash}), **base, "calendar_hash": calendar_hash, "available_at": available_at, "ingested_at": available_at})
    return output

def write_jsonl(path: Path, rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    identities = []
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(canonical_json(row) + "\n")
            count += 1
            for candidate in (
                "raw_revision_id",
                "fx_rate_revision_id",
                "action_id",
                "session_id",
                "status_id",
                "rejection_id",
            ):
                if candidate in row:
                    identities.append(str(row[candidate]))
                    break
    raw = path.read_bytes()
    return {"path": path.as_posix(), "row_count": count, "sha256": sha256_bytes(raw), "identity_set_sha256": sha256_json(sorted(identities))}

def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows = []
    try:
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise Wp04BackfillError(f"{path}:{line_number} must contain a JSON object")
                rows.append(value)
    except (OSError, json.JSONDecodeError) as exc:
        raise Wp04BackfillError(f"invalid JSONL {path}: {exc}") from exc
    return rows

def plan_identity(plan: Mapping[str, Any]) -> dict[str, Any]:
    keys = ("schema_version", "operation", "git_sha", "asset_set_version", "asset_set_sha256", "assets", "start_date", "end_date", "intraday_start_date", "hourly_start_date", "files", "total_row_count", "max_rows", "provider_versions", "production_change_allowed")
    return {key: plan[key] for key in keys}

def finalize_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(plan)
    result["plan_checksum"] = sha256_json(plan_identity(result))
    return result

def verify_plan_files(plan: Mapping[str, Any]) -> None:
    total = 0
    for label, metadata in plan["files"].items():
        path = Path(metadata["path"])
        if not path.is_file():
            raise Wp04BackfillError(f"planned file is missing: {label}")
        if sha256_bytes(path.read_bytes()) != metadata["sha256"]:
            raise Wp04BackfillError(f"planned file checksum mismatch: {label}")
        rows = read_jsonl(path)
        if len(rows) != int(metadata["row_count"]):
            raise Wp04BackfillError(f"planned file row count mismatch: {label}")
        total += len(rows)
    if total != int(plan["total_row_count"]):
        raise Wp04BackfillError("plan total_row_count mismatch")
    if total > int(plan["max_rows"]):
        raise Wp04BackfillError("plan exceeds max_rows")

def verify_plan_checksum(plan: Mapping[str, Any], expected: str) -> str:
    expected = str(expected or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", expected):
        raise Wp04BackfillError("expected_plan_checksum must be SHA-256")
    actual = sha256_json(plan_identity(plan))
    if actual != expected or str(plan.get("plan_checksum")) != expected:
        raise Wp04BackfillError(f"plan checksum mismatch: expected {expected}, actual {actual}")
    return actual

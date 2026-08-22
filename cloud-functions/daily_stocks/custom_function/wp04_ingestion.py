"""Shadow-only WP-04 price and corporate-action normalization.

This module does not mutate BigQuery. It converts provider payloads into
content-addressed JSONL records whose availability and interval lineage are
explicit. The BigQuery writer lives in ``wp04_bq_operations``.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import io
import json
import math
import uuid
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo

import requests

UTC = dt.timezone.utc
INTERVAL_SECONDS = {"15m": 900, "1h": 3600, "1d": 86400}


def _json_default(value: Any):
    if isinstance(value, dt.datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("datetime values must be timezone-aware")
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, dt.date):
        return value.isoformat()
    raise TypeError(type(value).__name__)


def canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        default=_json_default,
        allow_nan=False,
    )


def sha256_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def new_ingestion_run_id() -> str:
    return str(uuid.uuid4())


def validate_shadow_table(table_id: str, environment: str) -> str:
    parts = str(table_id or "").strip().split(".")
    if len(parts) != 3 or any(not part for part in parts):
        raise ValueError("BigQuery table must be project.dataset.table")
    if str(environment or "").strip().lower() != "shadow":
        raise ValueError("WP-04 writes are restricted to environment=shadow")
    if "shadow" not in parts[1].lower():
        raise ValueError("WP-04 destination dataset name must contain 'shadow'")
    return ".".join(parts)


def _aware(value: dt.datetime, timezone: str) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=ZoneInfo(timezone))
    return value.astimezone(UTC)


def _number(
    value: Any,
    label: str,
    *,
    positive: bool = False,
) -> float | None:
    if value is None or value == "":
        return None
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite")
    if positive and number <= 0:
        raise ValueError(f"{label} must be positive")
    return number


def normalize_price_record(
    payload: Mapping[str, Any],
    *,
    provider: str,
    provider_symbol: str,
    ticker: str,
    asset_type: str,
    exchange: str,
    source_interval: str,
    source_timezone: str,
    currency: str,
    ingestion_run_id: str,
    source_version: str,
    ingested_at: dt.datetime,
) -> dict[str, Any]:
    if source_interval not in INTERVAL_SECONDS:
        raise ValueError(f"unsupported source_interval {source_interval}")
    timestamp = payload.get("timestamp")
    if not isinstance(timestamp, dt.datetime):
        raise ValueError("payload timestamp must be datetime")
    bar_start = _aware(timestamp, source_timezone)
    bar_end = bar_start + dt.timedelta(
        seconds=INTERVAL_SECONDS[source_interval]
    )
    ingested_at = _aware(ingested_at, "UTC")
    published = payload.get("available_at")
    if published is None:
        available_at = bar_end
    elif not isinstance(published, dt.datetime):
        raise ValueError("available_at must be datetime")
    else:
        available_at = _aware(published, source_timezone)
    if available_at < bar_end:
        raise ValueError("available_at cannot precede bar_end")
    if ingested_at < available_at:
        raise ValueError("ingested_at cannot precede available_at")

    open_ = _number(payload.get("open"), "open", positive=True)
    high = _number(payload.get("high"), "high", positive=True)
    low = _number(payload.get("low"), "low", positive=True)
    close = _number(payload.get("close"), "close", positive=True)
    adjusted_close = _number(
        payload.get("adjusted_close"),
        "adjusted_close",
        positive=True,
    )
    volume = _number(payload.get("volume"), "volume")
    if volume is not None and volume < 0:
        raise ValueError("volume cannot be negative")
    if high < max(open_, low, close) or low > min(open_, high, close):
        raise ValueError("OHLC values are inconsistent")

    payload_for_hash = {
        key: value for key, value in payload.items() if key != "available_at"
    }
    payload_hash = sha256_json(payload_for_hash)
    logical_key = {
        "provider": provider,
        "provider_symbol": provider_symbol,
        "source_interval": source_interval,
        "bar_start": bar_start,
    }
    raw_record_id = "price_" + sha256_json(logical_key)
    source_record_id = str(payload.get("source_record_id") or raw_record_id)
    raw_revision_id = "price_revision_" + sha256_json(
        {
            **logical_key,
            "source_record_id": source_record_id,
            "payload_hash": payload_hash,
            "available_at": available_at,
        }
    )
    return {
        "raw_revision_id": raw_revision_id,
        "raw_record_id": raw_record_id,
        "ingestion_run_id": ingestion_run_id,
        "provider": provider.upper(),
        "provider_symbol": provider_symbol,
        "ticker": ticker.upper(),
        "asset_type": asset_type.upper(),
        "exchange": exchange.upper(),
        "source_interval": source_interval,
        "source_timezone": source_timezone,
        "bar_start": bar_start,
        "bar_end": bar_end,
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "adjusted_close": adjusted_close,
        "volume": volume,
        "currency": currency.upper(),
        "source_record_id": source_record_id,
        "source_version": source_version,
        "payload_hash": payload_hash,
        "available_at": available_at,
        "ingested_at": ingested_at,
        "quality_status": "RAW_VALIDATED",
    }


def yfinance_frame_records(
    frame,
    *,
    provider_symbol: str,
    ticker: str,
    asset_type: str,
    exchange: str,
    source_interval: str,
    currency: str,
    ingestion_run_id: str,
    source_version: str,
    ingested_at: dt.datetime,
) -> list[dict[str, Any]]:
    timezone = str(getattr(frame.index, "tz", None) or "UTC")
    records = []
    for index, row in frame.iterrows():
        payload = {
            "timestamp": (
                index.to_pydatetime()
                if hasattr(index, "to_pydatetime")
                else index
            ),
            "open": row.get("Open"),
            "high": row.get("High"),
            "low": row.get("Low"),
            "close": row.get("Close"),
            "adjusted_close": row.get("Adj Close"),
            "volume": row.get("Volume"),
        }
        records.append(
            normalize_price_record(
                payload,
                provider="YAHOO",
                provider_symbol=provider_symbol,
                ticker=ticker,
                asset_type=asset_type,
                exchange=exchange,
                source_interval=source_interval,
                source_timezone=timezone,
                currency=currency,
                ingestion_run_id=ingestion_run_id,
                source_version=source_version,
                ingested_at=ingested_at,
            )
        )
    return records


def normalize_corporate_actions(
    actions,
    *,
    ticker: str,
    provider: str,
    currency: str,
    ingestion_run_id: str,
    source_version: str,
    ingested_at: dt.datetime,
) -> list[dict[str, Any]]:
    """Normalize actions without fabricating historical publication times.

    Yahoo does not expose a reliable publication timestamp for historical
    actions. Backfilled rows use ingestion time as ``available_at`` and remain
    ineligible for historical PIT replay. They are still useful for adjustment
    lineage and prospective observations.
    """

    ingested_at = _aware(ingested_at, "UTC")
    output = []
    for index, row in actions.iterrows():
        ex_date = index.date() if hasattr(index, "date") else index
        for action_type, column, value_field in (
            ("DIVIDEND", "Dividends", "cash_amount"),
            ("SPLIT", "Stock Splits", "ratio"),
        ):
            value = _number(row.get(column), column)
            if value is None or value == 0:
                continue
            source_record_id = sha256_json(
                {
                    "provider": provider,
                    "ticker": ticker,
                    "action_type": action_type,
                    "ex_date": ex_date,
                    "value": value,
                    "source_version": source_version,
                }
            )
            action_id = "action_" + sha256_json(
                {
                    "source_record_id": source_record_id,
                    "revision": 1,
                    "available_at": ingested_at,
                }
            )
            document = {
                "action_id": action_id,
                "ingestion_run_id": ingestion_run_id,
                "ticker": ticker.upper(),
                "action_type": action_type,
                "ex_date": ex_date,
                "record_date": None,
                "pay_date": None,
                "ratio": None,
                "cash_amount": None,
                "currency": currency.upper(),
                "provider": provider.upper(),
                "source_record_id": source_record_id,
                "source_version": source_version,
                "source_published_at": None,
                "available_at": ingested_at,
                "ingested_at": ingested_at,
                "revision": 1,
                "backtest_eligible": False,
                "quality_status": "UNVERIFIED_AVAILABLE_AT",
            }
            document[value_field] = value
            output.append(document)
    return output


def fetch_stooq_daily(
    symbol: str,
    *,
    start_date: dt.date,
    end_date: dt.date,
    timeout_seconds: int = 30,
) -> list[dict[str, Any]]:
    response = requests.get(
        "https://stooq.com/q/d/l/",
        params={
            "s": symbol.lower(),
            "d1": start_date.strftime("%Y%m%d"),
            "d2": end_date.strftime("%Y%m%d"),
            "i": "d",
        },
        timeout=timeout_seconds,
        headers={"User-Agent": "FirstLayerStockMarket-WP04/1.0"},
    )
    response.raise_for_status()
    output = []
    for row in csv.DictReader(io.StringIO(response.text)):
        if not row.get("Date") or row.get("Close") in {None, "No data"}:
            continue
        day = dt.date.fromisoformat(row["Date"])
        output.append(
            {
                "timestamp": dt.datetime.combine(day, dt.time.min, tzinfo=UTC),
                "open": row["Open"],
                "high": row["High"],
                "low": row["Low"],
                "close": row["Close"],
                "adjusted_close": row["Close"],
                "volume": row.get("Volume"),
                "source_record_id": f"stooq:{symbol}:{day.isoformat()}",
            }
        )
    return output


def write_json_lines(
    path: str | Path,
    rows: Iterable[Mapping[str, Any]],
) -> int:
    count = 0
    with Path(path).open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(canonical_json(row) + "\n")
            count += 1
    return count

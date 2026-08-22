"""Provider-neutral normalization into append-only WP-04 raw observations."""

from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import Iterable, Mapping
from zoneinfo import ZoneInfo

from .calendar import interval_seconds
from .models import RawPriceObservation, UTC


def new_ingestion_run_id() -> str:
    return str(uuid.uuid4())


def normalize_rows(
    rows: Iterable[Mapping[str, object]],
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
) -> tuple[RawPriceObservation, ...]:
    timezone = ZoneInfo(source_timezone)
    duration = dt.timedelta(seconds=interval_seconds(source_interval))
    output = []
    for raw in rows:
        timestamp = raw.get("timestamp")
        if not isinstance(timestamp, dt.datetime):
            raise ValueError("provider row timestamp must be datetime")
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone)
        start = timestamp.astimezone(UTC)
        end = start + duration

        available = raw.get("available_at")
        if available is None:
            available = end
        if not isinstance(available, dt.datetime):
            raise ValueError("available_at must be datetime")
        if available.tzinfo is None:
            available = available.replace(tzinfo=timezone)

        output.append(
            RawPriceObservation(
                provider=provider,
                provider_symbol=provider_symbol,
                ticker=ticker,
                asset_type=asset_type,
                exchange=exchange,
                source_interval=source_interval,
                source_timezone=source_timezone,
                bar_start=start,
                bar_end=end,
                open=float(raw["open"]),
                high=float(raw["high"]),
                low=float(raw["low"]),
                close=float(raw["close"]),
                adjusted_close=(
                    None
                    if raw.get("adjusted_close") is None
                    else float(raw["adjusted_close"])
                ),
                volume=(
                    None if raw.get("volume") is None else float(raw["volume"])
                ),
                currency=currency,
                available_at=available,
                ingested_at=ingested_at,
                ingestion_run_id=ingestion_run_id,
                source_version=source_version,
                payload=dict(raw),
                source_record_id=(
                    None
                    if raw.get("source_record_id") is None
                    else str(raw["source_record_id"])
                ),
            )
        )
    return tuple(output)

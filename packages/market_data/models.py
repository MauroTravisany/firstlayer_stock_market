"""Typed, content-addressed market-data records used by WP-04."""

from __future__ import annotations

import dataclasses
import datetime as dt
import math
from typing import Any, Mapping

from packages.common.hashing import sha256_json

UTC = dt.timezone.utc
ALLOWED_ASSET_TYPES = {"STOCK", "ETF", "CRYPTO", "FX"}
ALLOWED_ACTION_TYPES = {"SPLIT", "DIVIDEND", "SYMBOL_CHANGE", "MERGER"}


def _aware_utc(value: dt.datetime, label: str) -> dt.datetime:
    if (
        not isinstance(value, dt.datetime)
        or value.tzinfo is None
        or value.utcoffset() is None
    ):
        raise ValueError(f"{label} must be timezone-aware")
    return value.astimezone(UTC)


def _finite(
    value: float | int | None,
    label: str,
    *,
    positive: bool = False,
) -> float | None:
    if value is None:
        return None
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{label} must be finite")
    if positive and number <= 0:
        raise ValueError(f"{label} must be positive")
    return number


@dataclasses.dataclass(frozen=True)
class RawPriceObservation:
    provider: str
    provider_symbol: str
    ticker: str
    asset_type: str
    exchange: str
    source_interval: str
    source_timezone: str
    bar_start: dt.datetime
    bar_end: dt.datetime
    open: float
    high: float
    low: float
    close: float
    adjusted_close: float | None
    volume: float | None
    currency: str
    available_at: dt.datetime
    ingested_at: dt.datetime
    ingestion_run_id: str
    source_version: str
    payload: Mapping[str, Any]
    source_record_id: str | None = None

    def __post_init__(self) -> None:
        for field in (
            "provider",
            "provider_symbol",
            "ticker",
            "exchange",
            "source_interval",
            "source_timezone",
            "currency",
            "ingestion_run_id",
            "source_version",
        ):
            value = str(getattr(self, field) or "").strip()
            if not value:
                raise ValueError(f"{field} is required")
            object.__setattr__(self, field, value)

        asset_type = str(self.asset_type or "").strip().upper()
        if asset_type not in ALLOWED_ASSET_TYPES:
            raise ValueError(f"unsupported asset_type {asset_type}")
        object.__setattr__(self, "asset_type", asset_type)

        start = _aware_utc(self.bar_start, "bar_start")
        end = _aware_utc(self.bar_end, "bar_end")
        available = _aware_utc(self.available_at, "available_at")
        ingested = _aware_utc(self.ingested_at, "ingested_at")
        if end <= start:
            raise ValueError("bar_end must be after bar_start")
        if available < end:
            raise ValueError("available_at cannot precede bar_end")
        if ingested < available:
            raise ValueError("ingested_at cannot precede available_at")
        object.__setattr__(self, "bar_start", start)
        object.__setattr__(self, "bar_end", end)
        object.__setattr__(self, "available_at", available)
        object.__setattr__(self, "ingested_at", ingested)

        open_ = _finite(self.open, "open", positive=True)
        high = _finite(self.high, "high", positive=True)
        low = _finite(self.low, "low", positive=True)
        close = _finite(self.close, "close", positive=True)
        adjusted = _finite(self.adjusted_close, "adjusted_close", positive=True)
        volume = _finite(self.volume, "volume")
        if volume is not None and volume < 0:
            raise ValueError("volume cannot be negative")
        if high < max(open_, close, low) or low > min(open_, close, high):
            raise ValueError("OHLC values are inconsistent")
        object.__setattr__(self, "open", open_)
        object.__setattr__(self, "high", high)
        object.__setattr__(self, "low", low)
        object.__setattr__(self, "close", close)
        object.__setattr__(self, "adjusted_close", adjusted)
        object.__setattr__(self, "volume", volume)
        if not isinstance(self.payload, Mapping):
            raise ValueError("payload must be a mapping")

    @property
    def payload_hash(self) -> str:
        return sha256_json(self.payload)

    @property
    def logical_key(self) -> Mapping[str, Any]:
        return {
            "provider": self.provider,
            "provider_symbol": self.provider_symbol,
            "source_interval": self.source_interval,
            "bar_start": self.bar_start,
        }

    @property
    def raw_record_id(self) -> str:
        return "price_" + sha256_json(self.logical_key)

    @property
    def raw_revision_id(self) -> str:
        return "price_revision_" + sha256_json(
            {
                **self.logical_key,
                "source_record_id": self.source_record_id,
                "payload_hash": self.payload_hash,
                "available_at": self.available_at,
            }
        )

    def as_row(self) -> dict[str, Any]:
        return {
            "raw_revision_id": self.raw_revision_id,
            "raw_record_id": self.raw_record_id,
            "ingestion_run_id": self.ingestion_run_id,
            "provider": self.provider,
            "provider_symbol": self.provider_symbol,
            "ticker": self.ticker,
            "asset_type": self.asset_type,
            "exchange": self.exchange,
            "source_interval": self.source_interval,
            "source_timezone": self.source_timezone,
            "bar_start": self.bar_start,
            "bar_end": self.bar_end,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "adjusted_close": self.adjusted_close,
            "volume": self.volume,
            "currency": self.currency,
            "source_record_id": self.source_record_id,
            "source_version": self.source_version,
            "payload_hash": self.payload_hash,
            "available_at": self.available_at,
            "ingested_at": self.ingested_at,
        }


@dataclasses.dataclass(frozen=True)
class CorporateAction:
    ticker: str
    action_type: str
    ex_date: dt.date
    available_at: dt.datetime
    ingested_at: dt.datetime
    provider: str
    source_record_id: str
    revision: int = 1
    ratio: float | None = None
    cash_amount: float | None = None
    currency: str | None = None
    record_date: dt.date | None = None
    pay_date: dt.date | None = None

    def __post_init__(self) -> None:
        action_type = str(self.action_type or "").upper()
        if action_type not in ALLOWED_ACTION_TYPES:
            raise ValueError(f"unsupported action_type {action_type}")
        object.__setattr__(self, "action_type", action_type)
        available = _aware_utc(self.available_at, "available_at")
        ingested = _aware_utc(self.ingested_at, "ingested_at")
        if ingested < available:
            raise ValueError("ingested_at cannot precede available_at")
        object.__setattr__(self, "available_at", available)
        object.__setattr__(self, "ingested_at", ingested)
        if self.revision < 1:
            raise ValueError("revision must be >= 1")
        if (
            action_type == "SPLIT"
            and _finite(self.ratio, "ratio", positive=True) is None
        ):
            raise ValueError("split ratio is required")
        if (
            action_type == "DIVIDEND"
            and _finite(self.cash_amount, "cash_amount") is None
        ):
            raise ValueError("dividend cash_amount is required")

    @property
    def action_id(self) -> str:
        return "action_" + sha256_json(
            {
                "provider": self.provider,
                "source_record_id": self.source_record_id,
                "ticker": self.ticker,
                "action_type": self.action_type,
                "ex_date": self.ex_date,
                "revision": self.revision,
                "ratio": self.ratio,
                "cash_amount": self.cash_amount,
                "currency": self.currency,
                "available_at": self.available_at,
            }
        )


@dataclasses.dataclass(frozen=True)
class SessionSpec:
    exchange: str
    asset_type: str
    session_date: dt.date
    open_utc: dt.datetime
    close_utc: dt.datetime
    session_status: str
    timezone: str

    def __post_init__(self) -> None:
        open_utc = _aware_utc(self.open_utc, "open_utc")
        close_utc = _aware_utc(self.close_utc, "close_utc")
        if close_utc <= open_utc:
            raise ValueError("close_utc must be after open_utc")
        object.__setattr__(self, "open_utc", open_utc)
        object.__setattr__(self, "close_utc", close_utc)


@dataclasses.dataclass(frozen=True)
class CanonicalBar:
    ticker: str
    asset_type: str
    exchange: str
    session_date: dt.date
    bar_start: dt.datetime
    bar_end: dt.datetime
    canonical_interval: str
    raw_open: float
    raw_high: float
    raw_low: float
    raw_close: float
    adjusted_close: float
    raw_volume: float | None
    currency: str
    provider: str
    source_interval: str
    coverage_ratio: float
    quality_status: str
    selected_by_rule: str
    available_at: dt.datetime
    source_revision_ids: tuple[str, ...]

    @property
    def price_id(self) -> str:
        return "canonical_price_" + sha256_json(
            {
                "ticker": self.ticker,
                "session_date": self.session_date,
                "canonical_interval": self.canonical_interval,
                "source_revision_ids": self.source_revision_ids,
                "selected_by_rule": self.selected_by_rule,
            }
        )


@dataclasses.dataclass(frozen=True)
class ReconciliationResult:
    ticker: str
    session_date: dt.date
    primary_provider: str
    secondary_provider: str | None
    status: str
    close_diff_bps: float | None
    volume_diff_ratio: float | None
    blocks_quality: bool
    reason: str

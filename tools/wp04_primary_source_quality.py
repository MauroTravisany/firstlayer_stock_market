"""Auditable row-level quality policy for mandatory WP-04 provider data.

A single malformed provider row must never be repaired silently and must not
hide the rest of a valid bounded series. Rows outside the canonical market
calendar or rows with invalid OHLCV are quarantined into checksum-bound status
artifacts. A mandatory series still fails closed when no valid rows remain or
when invalid in-session rows exceed a strict bounded tolerance.
"""

from __future__ import annotations

import datetime as dt
import math
from collections import Counter
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

from packages.common.hashing import sha256_json
from packages.market_data.calendar import interval_seconds, session_for_date


POLICY_VERSION = "wp04-primary-row-quarantine-v1"
PROVIDER = "YAHOO"
MIN_VALID_ROW_RATIO = 0.995
MAX_INVALID_ROWS_PER_SERIES = 5
PRICE_FIELDS = ("open", "high", "low", "close")
NY = ZoneInfo("America/New_York")
UTC = dt.timezone.utc


class ProviderRowValidationError(ValueError):
    """A provider payload is invalid for a stable reason code."""

    def __init__(self, reason_code: str, message: str):
        self.reason_code = str(reason_code).strip().upper()
        super().__init__(str(message).strip())


class PrimarySourceQualityError(ValueError):
    """A mandatory primary-provider series violates the quarantine policy."""


def _missing(value: Any) -> bool:
    if value is None or value == "":
        return True
    try:
        return bool(value != value)
    except Exception:
        return False


def _number(value: Any, label: str, *, required: bool) -> float | None:
    if _missing(value):
        if required:
            raise ProviderRowValidationError(
                "MISSING_REQUIRED_PRICE",
                f"{label} is missing",
            )
        return None
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise ProviderRowValidationError(
            "NON_NUMERIC_VALUE",
            f"{label} is not numeric",
        ) from exc
    if not math.isfinite(number):
        raise ProviderRowValidationError(
            "NON_FINITE_VALUE",
            f"{label} is not finite",
        )
    return number


def clean_price_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Validate OHLCV and return a typed payload without changing prices."""

    cleaned = dict(payload)
    values = {
        field: _number(payload.get(field), field, required=True)
        for field in PRICE_FIELDS
    }
    if any(value is None or value <= 0 for value in values.values()):
        raise ProviderRowValidationError(
            "NON_POSITIVE_PRICE",
            "required OHLC values must be positive",
        )

    scale = max(1.0, *(abs(float(value)) for value in values.values()))
    tolerance = scale * 1e-12
    if (
        float(values["high"]) + tolerance
        < max(float(values[field]) for field in PRICE_FIELDS)
        or float(values["low"]) - tolerance
        > min(float(values[field]) for field in PRICE_FIELDS)
    ):
        raise ProviderRowValidationError(
            "OHLC_INCONSISTENT",
            "provider OHLC values are inconsistent",
        )

    adjusted_close = _number(
        payload.get("adjusted_close"),
        "adjusted_close",
        required=False,
    )
    if adjusted_close is not None and adjusted_close <= 0:
        raise ProviderRowValidationError(
            "INVALID_ADJUSTED_CLOSE",
            "adjusted_close must be positive when present",
        )

    volume = _number(payload.get("volume"), "volume", required=False)
    if volume is not None and volume < 0:
        raise ProviderRowValidationError(
            "NEGATIVE_VOLUME",
            "volume cannot be negative",
        )

    cleaned.update(values)
    cleaned["adjusted_close"] = adjusted_close
    cleaned["volume"] = volume
    return cleaned


def _timestamp(value: Any) -> dt.datetime:
    if hasattr(value, "to_pydatetime"):
        value = value.to_pydatetime()
    if isinstance(value, dt.date) and not isinstance(value, dt.datetime):
        value = dt.datetime.combine(value, dt.time.min)
    if not isinstance(value, dt.datetime):
        raise PrimarySourceQualityError(
            "provider frame index must contain datetime values"
        )
    return value


def _aware(value: dt.datetime, timezone: str) -> dt.datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        value = value.replace(tzinfo=ZoneInfo(timezone))
    return value.astimezone(UTC)


def _session_day(
    timestamp: dt.datetime,
    *,
    exchange: str,
    asset_type: str,
    source_timezone: str,
) -> dt.date:
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        timestamp = timestamp.replace(tzinfo=ZoneInfo(source_timezone))
    if exchange.upper() == "XNYS" or asset_type.upper() in {"STOCK", "ETF"}:
        return timestamp.astimezone(NY).date()
    return timestamp.astimezone(UTC).date()


def _outside_canonical_session(
    timestamp: dt.datetime,
    *,
    exchange: str,
    asset_type: str,
    source_interval: str,
    source_timezone: str,
) -> bool:
    if asset_type.upper() == "CRYPTO":
        return False
    if source_interval not in {"1d", "15m"}:
        return False
    day = _session_day(
        timestamp,
        exchange=exchange,
        asset_type=asset_type,
        source_timezone=source_timezone,
    )
    session = session_for_date(day, exchange=exchange, asset_type=asset_type)
    if session is None:
        return True
    if source_interval == "1d":
        return False
    bar_start = _aware(timestamp, source_timezone)
    bar_end = bar_start + dt.timedelta(seconds=interval_seconds(source_interval))
    return bar_start < session.open_utc or bar_end > session.close_utc


def _hashable(value: Any) -> Any:
    if isinstance(value, dt.datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            return value.isoformat()
        return value.astimezone(UTC).isoformat()
    if isinstance(value, dt.date):
        return value.isoformat()
    if _missing(value):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    if math.isfinite(number):
        return number
    return str(value)


def _payload_hash(payload: Mapping[str, Any]) -> str:
    return sha256_json(
        {str(key): _hashable(value) for key, value in payload.items()}
    )


def _rejection(
    *,
    ticker: str,
    provider_symbol: str,
    asset_type: str,
    exchange: str,
    source_interval: str,
    source_timezone: str,
    event_time: dt.datetime,
    reason_code: str,
    payload_hash: str,
    observed_at: dt.datetime,
) -> dict[str, Any]:
    event_time_utc = _aware(event_time, source_timezone)
    identity = {
        "policy_version": POLICY_VERSION,
        "provider": PROVIDER,
        "ticker": ticker.upper(),
        "provider_symbol": provider_symbol,
        "source_interval": source_interval,
        "event_time": event_time_utc,
        "reason_code": reason_code,
        "payload_hash": payload_hash,
    }
    return {
        "rejection_id": "provider_rejection_" + sha256_json(identity),
        **identity,
        "asset_type": asset_type.upper(),
        "exchange": exchange.upper(),
        "source_timezone": source_timezone,
        "disposition": "QUARANTINED",
        "observed_at": observed_at.astimezone(UTC),
        "production_change_allowed": False,
    }


def normalize_yahoo_frame(
    frame: Any,
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
    normalizer: Callable[..., dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    """Normalize one mandatory Yahoo series with bounded row quarantine."""

    if ingested_at.tzinfo is None or ingested_at.utcoffset() is None:
        raise PrimarySourceQualityError("ingested_at must be timezone-aware")
    source_timezone = str(getattr(frame.index, "tz", None) or "UTC")
    accepted: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    reasons: Counter[str] = Counter()
    raw_count = 0
    off_session_count = 0
    invalid_count = 0

    for index, row in frame.iterrows():
        raw_count += 1
        event_time = _timestamp(index)
        payload = {
            "timestamp": event_time,
            "open": row.get("Open"),
            "high": row.get("High"),
            "low": row.get("Low"),
            "close": row.get("Close"),
            "adjusted_close": row.get("Adj Close"),
            "volume": row.get("Volume"),
        }
        payload_hash = _payload_hash(payload)

        if _outside_canonical_session(
            event_time,
            exchange=exchange,
            asset_type=asset_type,
            source_interval=source_interval,
            source_timezone=source_timezone,
        ):
            reason = "OUTSIDE_CANONICAL_SESSION"
            off_session_count += 1
            reasons[reason] += 1
            rejected.append(
                _rejection(
                    ticker=ticker,
                    provider_symbol=provider_symbol,
                    asset_type=asset_type,
                    exchange=exchange,
                    source_interval=source_interval,
                    source_timezone=source_timezone,
                    event_time=event_time,
                    reason_code=reason,
                    payload_hash=payload_hash,
                    observed_at=ingested_at,
                )
            )
            continue

        try:
            cleaned = clean_price_payload(payload)
        except ProviderRowValidationError as exc:
            invalid_count += 1
            reasons[exc.reason_code] += 1
            rejected.append(
                _rejection(
                    ticker=ticker,
                    provider_symbol=provider_symbol,
                    asset_type=asset_type,
                    exchange=exchange,
                    source_interval=source_interval,
                    source_timezone=source_timezone,
                    event_time=event_time,
                    reason_code=exc.reason_code,
                    payload_hash=payload_hash,
                    observed_at=ingested_at,
                )
            )
            continue

        try:
            accepted.append(
                normalizer(
                    cleaned,
                    provider=PROVIDER,
                    provider_symbol=provider_symbol,
                    ticker=ticker,
                    asset_type=asset_type,
                    exchange=exchange,
                    source_interval=source_interval,
                    source_timezone=source_timezone,
                    currency=currency,
                    ingestion_run_id=ingestion_run_id,
                    source_version=source_version,
                    ingested_at=ingested_at,
                )
            )
        except ValueError as exc:
            raise PrimarySourceQualityError(
                "validated provider row failed the normalization contract for "
                f"{ticker} {source_interval}: {exc}"
            ) from exc

    eligible_count = raw_count - off_session_count
    valid_ratio = (
        len(accepted) / eligible_count if eligible_count > 0 else 0.0
    )
    if not accepted:
        raise PrimarySourceQualityError(
            f"Yahoo has no valid {source_interval} rows for {ticker} after quarantine"
        )
    if invalid_count > MAX_INVALID_ROWS_PER_SERIES:
        raise PrimarySourceQualityError(
            f"Yahoo invalid-row count exceeds policy for {ticker} {source_interval}: "
            f"{invalid_count} > {MAX_INVALID_ROWS_PER_SERIES}"
        )
    if eligible_count > 0 and valid_ratio < MIN_VALID_ROW_RATIO:
        raise PrimarySourceQualityError(
            f"Yahoo valid-row ratio is below policy for {ticker} {source_interval}: "
            f"{valid_ratio:.6f} < {MIN_VALID_ROW_RATIO:.6f}"
        )

    status_identity = {
        "policy_version": POLICY_VERSION,
        "provider": PROVIDER,
        "ticker": ticker.upper(),
        "provider_symbol": provider_symbol,
        "source_interval": source_interval,
        "ingestion_run_id": ingestion_run_id,
    }
    status = {
        "status_id": "provider_status_" + sha256_json(status_identity),
        **status_identity,
        "asset_type": asset_type.upper(),
        "exchange": exchange.upper(),
        "required": True,
        "status": (
            "AVAILABLE" if not rejected else "AVAILABLE_WITH_QUARANTINE"
        ),
        "raw_row_count": raw_count,
        "eligible_row_count": eligible_count,
        "accepted_row_count": len(accepted),
        "rejected_row_count": len(rejected),
        "off_session_row_count": off_session_count,
        "invalid_row_count": invalid_count,
        "valid_row_ratio": valid_ratio,
        "minimum_valid_row_ratio": MIN_VALID_ROW_RATIO,
        "maximum_invalid_rows": MAX_INVALID_ROWS_PER_SERIES,
        "reason_counts": dict(sorted(reasons.items())),
        "observed_at": ingested_at.astimezone(UTC),
        "production_change_allowed": False,
    }
    return accepted, status, rejected

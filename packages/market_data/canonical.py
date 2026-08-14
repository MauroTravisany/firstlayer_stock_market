"""Canonical daily and four-hour price construction with fail-closed selection."""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from typing import Iterable

from packages.common.hashing import sha256_json

from .calendar import expected_bars, interval_seconds
from .models import CanonicalBar, RawPriceObservation, SessionSpec


def _latest_by_start(
    rows: Iterable[RawPriceObservation],
) -> list[RawPriceObservation]:
    selected: dict[dt.datetime, RawPriceObservation] = {}
    for row in rows:
        previous = selected.get(row.bar_start)
        if previous is None or (
            row.available_at,
            row.ingested_at,
            row.raw_revision_id,
        ) > (
            previous.available_at,
            previous.ingested_at,
            previous.raw_revision_id,
        ):
            selected[row.bar_start] = row
    return [selected[key] for key in sorted(selected)]


def _validate_common(rows: list[RawPriceObservation]) -> None:
    if not rows:
        raise ValueError("at least one observation is required")
    keys = {
        (row.ticker, row.asset_type, row.exchange, row.currency, row.provider)
        for row in rows
    }
    if len(keys) != 1:
        raise ValueError(
            "canonicalization cannot mix ticker, asset, exchange, currency or provider"
        )


def canonicalize_session(
    observations: Iterable[RawPriceObservation],
    session: SessionSpec,
    *,
    intraday_interval: str = "15m",
    minimum_coverage: float = 0.95,
) -> CanonicalBar:
    rows = [
        row
        for row in observations
        if row.bar_start < session.close_utc and row.bar_end > session.open_utc
    ]
    _validate_common(rows)
    if not 0 < minimum_coverage <= 1:
        raise ValueError("minimum_coverage must be in (0,1]")

    daily = _latest_by_start(
        row for row in rows if row.source_interval.lower() == "1d"
    )
    intraday = _latest_by_start(
        row
        for row in rows
        if row.source_interval.lower() == intraday_interval.lower()
    )
    expected = expected_bars(session, intraday_interval)
    coverage = min(1.0, len(intraday) / expected) if expected else 0.0
    complete = bool(intraday) and coverage >= minimum_coverage

    if complete:
        if any(
            row.bar_start < session.open_utc or row.bar_end > session.close_utc
            for row in intraday
        ):
            raise ValueError("intraday bars escape the canonical session")
        chosen = intraday
        selected_by_rule = "INTRADAY_COMPLETE"
        quality = (
            "CANONICAL_RECONCILED"
            if coverage == 1.0
            else "CANONICAL_COVERAGE_ACCEPTED"
        )
        source_interval = intraday_interval
        raw_open = chosen[0].open
        raw_high = max(row.high for row in chosen)
        raw_low = min(row.low for row in chosen)
        raw_close = chosen[-1].close
        raw_volume = sum((row.volume or 0.0) for row in chosen)
        adjusted_close = chosen[-1].adjusted_close or raw_close
        available_at = max(row.available_at for row in chosen)
    elif daily:
        chosen = [
            max(
                daily,
                key=lambda row: (
                    row.available_at,
                    row.ingested_at,
                    row.raw_revision_id,
                ),
            )
        ]
        selected_by_rule = (
            "DAILY_FALLBACK_NO_INTRADAY"
            if not intraday
            else "DAILY_FALLBACK_INCOMPLETE_INTRADAY"
        )
        quality = "CANONICAL_DAILY_FALLBACK"
        source_interval = "1d"
        row = chosen[0]
        raw_open = row.open
        raw_high = row.high
        raw_low = row.low
        raw_close = row.close
        raw_volume = row.volume
        adjusted_close = row.adjusted_close or row.close
        available_at = row.available_at
    else:
        raise ValueError(
            "no complete intraday series or daily fallback is available"
        )

    first = chosen[0]
    return CanonicalBar(
        ticker=first.ticker,
        asset_type=first.asset_type,
        exchange=first.exchange,
        session_date=session.session_date,
        bar_start=session.open_utc,
        bar_end=session.close_utc,
        canonical_interval="1d",
        raw_open=raw_open,
        raw_high=raw_high,
        raw_low=raw_low,
        raw_close=raw_close,
        adjusted_close=adjusted_close,
        raw_volume=raw_volume,
        currency=first.currency,
        provider=first.provider,
        source_interval=source_interval,
        coverage_ratio=coverage,
        quality_status=quality,
        selected_by_rule=selected_by_rule,
        available_at=available_at,
        source_revision_ids=tuple(row.raw_revision_id for row in chosen),
    )


def canonicalize_crypto_4h(
    observations: Iterable[RawPriceObservation],
) -> tuple[CanonicalBar, ...]:
    rows = sorted(
        observations,
        key=lambda row: (row.bar_start, row.available_at, row.ingested_at),
    )
    _validate_common(rows)
    if rows[0].asset_type != "CRYPTO":
        raise ValueError(
            "4h crypto canonicalization requires CRYPTO observations"
        )
    if any(interval_seconds(row.source_interval) != 3600 for row in rows):
        raise ValueError("crypto 4h canonicalization requires 1h source bars")

    latest = _latest_by_start(rows)
    buckets: dict[dt.datetime, list[RawPriceObservation]] = defaultdict(list)
    for row in latest:
        start = row.bar_start.astimezone(dt.timezone.utc)
        bucket = start.replace(
            hour=(start.hour // 4) * 4,
            minute=0,
            second=0,
            microsecond=0,
        )
        buckets[bucket].append(row)

    output = []
    for bucket, group in sorted(buckets.items()):
        expected_starts = {
            bucket + dt.timedelta(hours=index) for index in range(4)
        }
        actual_starts = {row.bar_start for row in group}
        if actual_starts != expected_starts:
            continue
        first = group[0]
        output.append(
            CanonicalBar(
                ticker=first.ticker,
                asset_type="CRYPTO",
                exchange=first.exchange,
                session_date=bucket.date(),
                bar_start=bucket,
                bar_end=bucket + dt.timedelta(hours=4),
                canonical_interval="4h",
                raw_open=group[0].open,
                raw_high=max(row.high for row in group),
                raw_low=min(row.low for row in group),
                raw_close=group[-1].close,
                adjusted_close=group[-1].adjusted_close or group[-1].close,
                raw_volume=sum((row.volume or 0.0) for row in group),
                currency=first.currency,
                provider=first.provider,
                source_interval="1h",
                coverage_ratio=1.0,
                quality_status="CANONICAL_RECONCILED",
                selected_by_rule="CRYPTO_4H_COMPLETE",
                available_at=max(row.available_at for row in group),
                source_revision_ids=tuple(
                    row.raw_revision_id for row in group
                ),
            )
        )
    return tuple(output)


def total_return(
    previous_raw_close: float,
    current_raw_close: float,
    *,
    split_ratio: float = 1.0,
    dividend: float = 0.0,
) -> float:
    if (
        previous_raw_close <= 0
        or current_raw_close <= 0
        or split_ratio <= 0
    ):
        raise ValueError("prices and split_ratio must be positive")
    return (
        current_raw_close * split_ratio + dividend
    ) / previous_raw_close - 1.0


def canonical_checksum(bars: Iterable[CanonicalBar]) -> str:
    rows = sorted(
        (
            {
                "price_id": bar.price_id,
                "ticker": bar.ticker,
                "session_date": bar.session_date,
                "interval": bar.canonical_interval,
                "raw_open": bar.raw_open,
                "raw_high": bar.raw_high,
                "raw_low": bar.raw_low,
                "raw_close": bar.raw_close,
                "adjusted_close": bar.adjusted_close,
                "raw_volume": bar.raw_volume,
                "coverage_ratio": bar.coverage_ratio,
                "quality_status": bar.quality_status,
                "selected_by_rule": bar.selected_by_rule,
                "source_revision_ids": bar.source_revision_ids,
            }
            for bar in bars
        ),
        key=lambda row: (
            row["ticker"],
            row["session_date"],
            row["interval"],
        ),
    )
    if not rows:
        raise ValueError("at least one canonical bar is required")
    return sha256_json(rows)

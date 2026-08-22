"""Deterministic XNYS, FX 24/5 and crypto 24/7 session calendars."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from .models import SessionSpec, UTC

NY = ZoneInfo("America/New_York")


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> dt.date:
    first = dt.date(year, month, 1)
    delta = (weekday - first.weekday()) % 7
    return first + dt.timedelta(days=delta + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> dt.date:
    next_month = (
        dt.date(year + 1, 1, 1)
        if month == 12
        else dt.date(year, month + 1, 1)
    )
    day = next_month - dt.timedelta(days=1)
    return day - dt.timedelta(days=(day.weekday() - weekday) % 7)


def _observed(day: dt.date) -> dt.date:
    if day.weekday() == 5:
        return day - dt.timedelta(days=1)
    if day.weekday() == 6:
        return day + dt.timedelta(days=1)
    return day


def _easter(year: int) -> dt.date:
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    day = ((h + l - 7 * m + 114) % 31) + 1
    return dt.date(year, month, day)


def xnys_holidays(year: int) -> set[dt.date]:
    holidays = {
        _observed(dt.date(year, 1, 1)),
        _nth_weekday(year, 1, 0, 3),
        _nth_weekday(year, 2, 0, 3),
        _easter(year) - dt.timedelta(days=2),
        _last_weekday(year, 5, 0),
        _observed(dt.date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),
        _nth_weekday(year, 11, 3, 4),
        _observed(dt.date(year, 12, 25)),
    }
    if year >= 2022:
        holidays.add(_observed(dt.date(year, 6, 19)))
    return holidays


def fx_holidays(year: int) -> set[dt.date]:
    """Return deterministic global FX closures used by the WP-04 calendar.

    Spot FX is modeled as 24/5 but not as open on the two universally closed
    year-end holidays. The following year's New Year's Day is included when its
    observed date falls in ``year`` (for example 2021-12-31 for 2022-01-01).
    The scope is deliberately narrow; venue- or currency-specific holidays are
    not inferred without a separate versioned calendar source.
    """

    candidates = (
        dt.date(year, 1, 1),
        dt.date(year, 12, 25),
        dt.date(year + 1, 1, 1),
    )
    return {
        observed
        for holiday in candidates
        for observed in (_observed(holiday),)
        if observed.year == year
    }


def _is_early_close(day: dt.date) -> bool:
    thanksgiving = _nth_weekday(day.year, 11, 3, 4)
    if day == thanksgiving + dt.timedelta(days=1):
        return True
    july3 = dt.date(day.year, 7, 3)
    return (
        day == july3
        and day.weekday() < 5
        and july3 not in xnys_holidays(day.year)
    )


def session_for_date(
    day: dt.date,
    *,
    exchange: str = "XNYS",
    asset_type: str = "STOCK",
) -> SessionSpec | None:
    asset_type = asset_type.upper()
    exchange = exchange.upper()
    if asset_type == "CRYPTO" or exchange == "CRYPTO_24_7":
        open_utc = dt.datetime.combine(day, dt.time.min, tzinfo=UTC)
        return SessionSpec(
            "CRYPTO_24_7",
            "CRYPTO",
            day,
            open_utc,
            open_utc + dt.timedelta(days=1),
            "OPEN",
            "UTC",
        )
    if asset_type == "FX" or exchange == "FX_24_5":
        if day.weekday() >= 5 or day in fx_holidays(day.year):
            return None
        open_utc = dt.datetime.combine(day, dt.time.min, tzinfo=UTC)
        return SessionSpec(
            "FX_24_5",
            "FX",
            day,
            open_utc,
            open_utc + dt.timedelta(days=1),
            "OPEN",
            "UTC",
        )
    if exchange != "XNYS":
        raise ValueError(f"unsupported exchange {exchange}")
    if day.weekday() >= 5 or day in xnys_holidays(day.year):
        return None
    close_time = dt.time(13, 0) if _is_early_close(day) else dt.time(16, 0)
    open_local = dt.datetime.combine(day, dt.time(9, 30), tzinfo=NY)
    close_local = dt.datetime.combine(day, close_time, tzinfo=NY)
    return SessionSpec(
        "XNYS",
        asset_type,
        day,
        open_local.astimezone(UTC),
        close_local.astimezone(UTC),
        "EARLY_CLOSE" if close_time.hour == 13 else "OPEN",
        "America/New_York",
    )


def iter_sessions(
    start: dt.date,
    end: dt.date,
    *,
    exchange: str = "XNYS",
    asset_type: str = "STOCK",
):
    if end < start:
        raise ValueError("end cannot precede start")
    day = start
    while day <= end:
        session = session_for_date(day, exchange=exchange, asset_type=asset_type)
        if session is not None:
            yield session
        day += dt.timedelta(days=1)


def interval_seconds(interval: str) -> int:
    value = interval.strip().lower()
    if len(value) < 2:
        raise ValueError(f"unsupported interval {interval}")
    unit = value[-1]
    amount = int(value[:-1])
    multipliers = {"m": 60, "h": 3600, "d": 86400}
    if amount <= 0 or unit not in multipliers:
        raise ValueError(f"unsupported interval {interval}")
    return amount * multipliers[unit]


def expected_bars(session: SessionSpec, interval: str) -> int:
    seconds = interval_seconds(interval)
    duration = int((session.close_utc - session.open_utc).total_seconds())
    if duration % seconds:
        raise ValueError("session duration is not divisible by interval")
    return duration // seconds

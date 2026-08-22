"""Configurable, challenge-aware WP-04 secondary market-data access.

Stooq is a configurable reconciliation source, not the primary price source.
This module never attempts to solve or bypass JavaScript/CAPTCHA challenges. It
classifies provider failures into sanitized reason codes so the bounded planner
can either fail closed (required mode) or continue with auditable single-source
quality (optional mode).
"""

from __future__ import annotations

import csv
import datetime as dt
import io
from typing import Any, Callable, Mapping

import requests


POLICY_VERSION = "wp04-secondary-source-configurable-v1"
PROVIDER = "STOOQ"
SOURCE_VERSION = "stooq-csv-v2"
CSV_ENDPOINT = "https://stooq.com/q/d/l/"
REQUIRED_COLUMNS = frozenset({"Date", "Open", "High", "Low", "Close"})
CHALLENGE_MARKERS = (
    "enable javascript",
    "javascript is required",
    "just a moment",
    "cf-chl-",
    "challenge-platform",
    "captcha",
    "verify you are human",
)


class SecondarySourceUnavailable(RuntimeError):
    """A secondary provider could not return a validated machine payload."""

    def __init__(self, reason_code: str, message: str):
        self.provider = PROVIDER
        self.reason_code = str(reason_code).strip().upper()
        super().__init__(str(message).strip())


def _looks_like_html(text: str, content_type: str) -> bool:
    stripped = text.lstrip().lower()
    return (
        "text/html" in content_type.lower()
        or stripped.startswith("<!doctype html")
        or stripped.startswith("<html")
        or "<script" in stripped[:4096]
    )


def _challenge_reason(text: str) -> str | None:
    lowered = text.lower()[:16384]
    if any(marker in lowered for marker in CHALLENGE_MARKERS):
        return "JAVASCRIPT_CHALLENGE"
    return None


def parse_stooq_csv(text: str, *, symbol: str) -> list[dict[str, Any]]:
    """Parse a validated Stooq daily CSV response into provider payloads."""

    body = str(text or "")
    challenge = _challenge_reason(body)
    if challenge:
        raise SecondarySourceUnavailable(
            challenge,
            f"Stooq returned an access challenge for {symbol}",
        )
    if _looks_like_html(body, ""):
        raise SecondarySourceUnavailable(
            "HTML_RESPONSE",
            f"Stooq returned HTML instead of CSV for {symbol}",
        )

    reader = csv.DictReader(io.StringIO(body))
    fieldnames = set(reader.fieldnames or ())
    missing = sorted(REQUIRED_COLUMNS - fieldnames)
    if missing:
        raise SecondarySourceUnavailable(
            "INVALID_CSV_SCHEMA",
            f"Stooq CSV for {symbol} is missing columns: {missing}",
        )

    output: list[dict[str, Any]] = []
    try:
        for row in reader:
            if not row.get("Date") or row.get("Close") in {None, "", "No data"}:
                continue
            day = dt.date.fromisoformat(str(row["Date"]))
            output.append(
                {
                    "timestamp": dt.datetime.combine(
                        day,
                        dt.time.min,
                        tzinfo=dt.timezone.utc,
                    ),
                    "open": row["Open"],
                    "high": row["High"],
                    "low": row["Low"],
                    "close": row["Close"],
                    "adjusted_close": row["Close"],
                    "volume": row.get("Volume"),
                    "source_record_id": f"stooq:{symbol}:{day.isoformat()}",
                }
            )
    except (KeyError, TypeError, ValueError) as exc:
        raise SecondarySourceUnavailable(
            "INVALID_CSV_ROW",
            f"Stooq returned an invalid CSV row for {symbol}",
        ) from exc

    if not output:
        raise SecondarySourceUnavailable(
            "NO_DATA",
            f"Stooq returned no daily rows for {symbol}",
        )
    return output


def fetch_stooq_daily(
    symbol: str,
    *,
    start_date: dt.date,
    end_date: dt.date,
    timeout_seconds: int = 30,
    api_key: str | None = None,
    get: Callable[..., Any] = requests.get,
) -> list[dict[str, Any]]:
    """Fetch Stooq CSV without bypassing access controls or persisting HTML."""

    params = {
        "s": str(symbol).strip().lower(),
        "d1": start_date.strftime("%Y%m%d"),
        "d2": end_date.strftime("%Y%m%d"),
        "i": "d",
    }
    if str(api_key or "").strip():
        params["apikey"] = str(api_key).strip()

    try:
        response = get(
            CSV_ENDPOINT,
            params=params,
            timeout=int(timeout_seconds),
            headers={
                "Accept": "text/csv,text/plain;q=0.9,*/*;q=0.1",
                "User-Agent": "FirstLayerStockMarket-WP04/2.0",
            },
        )
    except requests.RequestException as exc:
        raise SecondarySourceUnavailable(
            "NETWORK_ERROR",
            f"Stooq request failed for {symbol}",
        ) from exc

    status_code = int(getattr(response, "status_code", 0) or 0)
    text = str(getattr(response, "text", "") or "")
    headers: Mapping[str, Any] = getattr(response, "headers", {}) or {}
    content_type = str(headers.get("Content-Type") or "")

    challenge = _challenge_reason(text)
    if challenge:
        raise SecondarySourceUnavailable(
            challenge,
            f"Stooq returned an access challenge for {symbol}",
        )
    if status_code == 429:
        raise SecondarySourceUnavailable(
            "RATE_LIMITED",
            f"Stooq rate-limited {symbol}",
        )
    if status_code in {401, 403}:
        raise SecondarySourceUnavailable(
            "ACCESS_DENIED",
            f"Stooq denied access for {symbol}",
        )
    if status_code < 200 or status_code >= 300:
        raise SecondarySourceUnavailable(
            "HTTP_ERROR",
            f"Stooq returned HTTP {status_code} for {symbol}",
        )
    if _looks_like_html(text, content_type):
        raise SecondarySourceUnavailable(
            "HTML_RESPONSE",
            f"Stooq returned HTML instead of CSV for {symbol}",
        )
    return parse_stooq_csv(text, symbol=symbol)


def status_document(
    *,
    ticker: str,
    provider_symbol: str,
    status: str,
    reason_code: str | None,
    required: bool,
    api_key_configured: bool,
    row_count: int,
    observed_at: dt.datetime,
) -> dict[str, Any]:
    """Return a sanitized, content-addressable provider-status record."""

    if observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware")
    normalized_status = str(status).strip().upper()
    if normalized_status not in {"AVAILABLE", "UNAVAILABLE"}:
        raise ValueError("secondary source status is invalid")
    count = int(row_count)
    if count < 0 or (normalized_status == "AVAILABLE" and count <= 0):
        raise ValueError("secondary source row_count is invalid")
    if normalized_status == "UNAVAILABLE" and count != 0:
        raise ValueError("unavailable secondary source must have zero rows")
    return {
        "policy_version": POLICY_VERSION,
        "provider": PROVIDER,
        "ticker": str(ticker).strip().upper(),
        "provider_symbol": str(provider_symbol).strip().lower(),
        "status": normalized_status,
        "reason_code": (
            None if reason_code is None else str(reason_code).strip().upper()
        ),
        "required": bool(required),
        "authentication_mode": (
            "API_KEY" if api_key_configured else "ANONYMOUS"
        ),
        "row_count": count,
        "observed_at": observed_at.astimezone(dt.timezone.utc),
        "production_change_allowed": False,
    }

"""Official, checksum-addressed USD/CLP reference-rate ingestion for WP-04.

The Banco Central de Chile BDE series ``F073.TCO.PRE.Z.D`` is the mandatory
historical USD/CLP reference source. The API token is supplied only to the HTTP
request and is never stored in rows, plans, logs, or status evidence.

The BDE response exposes a rate date but not a machine-verifiable publication
timestamp. To remain point-in-time safe, each observation becomes usable only
at the next local midnight in ``America/Santiago``. This is deliberately more
conservative than the official same-banking-day publication.
"""

from __future__ import annotations

import datetime as dt
import math
from collections import Counter
from decimal import Decimal, InvalidOperation
from typing import Any, Callable, Mapping
from zoneinfo import ZoneInfo

import requests

from packages.common.hashing import sha256_json


POLICY_VERSION = "wp04-bcch-observed-dollar-v1"
SOURCE_VERSION = "bcch-bde-rest-v1"
PROVIDER = "BCCH_BDE"
SERIES_ID = "F073.TCO.PRE.Z.D"
ENDPOINT = "https://si3.bcentral.cl/SieteRestWS/SieteRestWS.ashx"
SOURCE_TIMEZONE = "America/Santiago"
QUALITY_STATUS = "RAW_REFERENCE_RATE_VALIDATED"
AVAILABILITY_POLICY = "CONSERVATIVE_NEXT_LOCAL_DAY"
UTC = dt.timezone.utc
SANTIAGO = ZoneInfo(SOURCE_TIMEZONE)


class BcchFxSourceError(RuntimeError):
    """The official BDE source could not produce an auditable reference series."""

    def __init__(self, reason_code: str, message: str):
        self.provider = PROVIDER
        self.reason_code = str(reason_code).strip().upper()
        super().__init__(str(message).strip())


def _parse_date(value: Any) -> dt.date:
    text = str(value or "").strip()
    for pattern in ("%d-%m-%Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    raise BcchFxSourceError(
        "INVALID_OBSERVATION_DATE",
        "Banco Central de Chile returned an invalid observation date",
    )


def _parse_rate(value: Any) -> float:
    text = str(value or "").strip()
    if not text:
        raise BcchFxSourceError(
            "MISSING_OBSERVATION_VALUE",
            "Banco Central de Chile returned a missing observation value",
        )
    normalized = text.replace(",", ".")
    try:
        decimal_value = Decimal(normalized)
    except InvalidOperation as exc:
        raise BcchFxSourceError(
            "NON_NUMERIC_OBSERVATION",
            "Banco Central de Chile returned a non-numeric observation",
        ) from exc
    number = float(decimal_value)
    if not math.isfinite(number) or number <= 0:
        raise BcchFxSourceError(
            "INVALID_OBSERVATION_VALUE",
            "Banco Central de Chile returned a non-positive or non-finite rate",
        )
    return number


def _local_midnight(day: dt.date) -> dt.datetime:
    return dt.datetime.combine(day, dt.time.min, tzinfo=SANTIAGO)


def _reference_row(
    *,
    rate_date: dt.date,
    rate: float,
    status_code: str,
    ticker: str,
    series_id: str,
    ingestion_run_id: str,
    ingested_at: dt.datetime,
) -> dict[str, Any]:
    if ingested_at.tzinfo is None or ingested_at.utcoffset() is None:
        raise BcchFxSourceError(
            "INVALID_INGESTION_TIME",
            "ingested_at must be timezone-aware",
        )
    bar_start = _local_midnight(rate_date)
    bar_end = _local_midnight(rate_date + dt.timedelta(days=1))
    available_at = bar_end
    if ingested_at.astimezone(UTC) < available_at.astimezone(UTC):
        raise BcchFxSourceError(
            "OBSERVATION_NOT_YET_ELIGIBLE",
            "official reference observation has not reached conservative availability",
        )
    payload = {
        "series_id": series_id,
        "rate_date": rate_date,
        "value": rate,
        "status_code": status_code,
        "availability_policy": AVAILABILITY_POLICY,
    }
    payload_hash = sha256_json(payload)
    logical_key = {
        "provider": PROVIDER,
        "provider_symbol": series_id,
        "source_interval": "1d",
        "bar_start": bar_start,
    }
    source_record_id = f"bcch:{series_id}:{rate_date.isoformat()}"
    raw_record_id = "price_" + sha256_json(logical_key)
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
        "provider": PROVIDER,
        "provider_symbol": series_id,
        "ticker": str(ticker).strip().upper(),
        "asset_type": "FX",
        "exchange": "FX_24_5",
        "source_interval": "1d",
        "source_timezone": SOURCE_TIMEZONE,
        "bar_start": bar_start,
        "bar_end": bar_end,
        "open": None,
        "high": None,
        "low": None,
        "close": None,
        "adjusted_close": rate,
        "volume": None,
        "currency": "CLP",
        "source_record_id": source_record_id,
        "source_version": SOURCE_VERSION,
        "payload_hash": payload_hash,
        "available_at": available_at,
        "ingested_at": ingested_at,
        "quality_status": QUALITY_STATUS,
    }


def _response_document(response: Any) -> Mapping[str, Any]:
    try:
        document = response.json()
    except (TypeError, ValueError) as exc:
        raise BcchFxSourceError(
            "INVALID_JSON_RESPONSE",
            "Banco Central de Chile returned invalid JSON",
        ) from exc
    if not isinstance(document, Mapping):
        raise BcchFxSourceError(
            "INVALID_RESPONSE_SHAPE",
            "Banco Central de Chile response root must be an object",
        )
    return document


def fetch_bcch_observed_dollar(
    *,
    token: str | None,
    start_date: dt.date,
    end_date: dt.date,
    ingestion_run_id: str,
    ingested_at: dt.datetime,
    ticker: str = "CLP=X",
    series_id: str = SERIES_ID,
    timeout_seconds: int = 30,
    get: Callable[..., Any] = requests.get,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fetch official observations and return reference rows plus status."""

    secret = str(token or "").strip()
    if not secret:
        raise BcchFxSourceError(
            "MISSING_API_TOKEN",
            "BCCH_API_TOKEN is required for the official USD/CLP reference source",
        )
    if end_date < start_date:
        raise BcchFxSourceError("INVALID_DATE_RANGE", "end_date cannot precede start_date")
    if not str(ingestion_run_id or "").strip():
        raise BcchFxSourceError("MISSING_INGESTION_RUN_ID", "ingestion_run_id is required")
    try:
        response = get(
            ENDPOINT,
            params={
                "token": secret,
                "function": "GetSeries",
                "timeseries": series_id,
                "firstdate": start_date.isoformat(),
                "lastdate": end_date.isoformat(),
            },
            timeout=int(timeout_seconds),
            headers={
                "Accept": "application/json",
                "User-Agent": "FirstLayerStockMarket-WP04/3.0",
            },
        )
    except requests.RequestException as exc:
        raise BcchFxSourceError("NETWORK_ERROR", "Banco Central de Chile request failed") from exc

    http_status = int(getattr(response, "status_code", 0) or 0)
    if http_status == 429:
        raise BcchFxSourceError("RATE_LIMITED", "Banco Central de Chile rate-limited the request")
    if http_status in {401, 403}:
        raise BcchFxSourceError("AUTHENTICATION_FAILED", "Banco Central de Chile rejected the API token")
    if http_status < 200 or http_status >= 300:
        raise BcchFxSourceError("HTTP_ERROR", f"Banco Central de Chile returned HTTP {http_status}")

    document = _response_document(response)
    try:
        code = int(document.get("Codigo"))
    except (TypeError, ValueError) as exc:
        raise BcchFxSourceError("INVALID_RESPONSE_CODE", "Banco Central de Chile response code is invalid") from exc
    if code != 0:
        raise BcchFxSourceError("API_ERROR", "Banco Central de Chile returned a non-success response")

    series = document.get("Series")
    if not isinstance(series, Mapping):
        raise BcchFxSourceError("INVALID_SERIES_SHAPE", "Banco Central de Chile response is missing Series")
    if str(series.get("seriesId") or "").strip() != series_id:
        raise BcchFxSourceError("SERIES_ID_MISMATCH", "Banco Central de Chile returned an unexpected series")
    observations = series.get("Obs")
    if not isinstance(observations, list):
        raise BcchFxSourceError("INVALID_OBSERVATIONS_SHAPE", "Banco Central de Chile response is missing Series.Obs")

    rows: list[dict[str, Any]] = []
    seen_dates: set[dt.date] = set()
    skipped_statuses: Counter[str] = Counter()
    for raw in observations:
        if not isinstance(raw, Mapping):
            raise BcchFxSourceError("INVALID_OBSERVATION_SHAPE", "Banco Central de Chile observation must be an object")
        rate_date = _parse_date(raw.get("indexDateString"))
        if rate_date < start_date or rate_date > end_date:
            raise BcchFxSourceError("OBSERVATION_OUTSIDE_RANGE", "Banco Central de Chile returned an observation outside the request")
        if rate_date in seen_dates:
            raise BcchFxSourceError("DUPLICATE_OBSERVATION_DATE", "Banco Central de Chile returned a duplicate observation date")
        seen_dates.add(rate_date)
        observation_status = str(raw.get("statusCode") or "").strip().upper()
        if observation_status != "OK":
            skipped_statuses[observation_status or "<MISSING>"] += 1
            continue
        rows.append(
            _reference_row(
                rate_date=rate_date,
                rate=_parse_rate(raw.get("value")),
                status_code=observation_status,
                ticker=ticker,
                series_id=series_id,
                ingestion_run_id=ingestion_run_id,
                ingested_at=ingested_at,
            )
        )

    if not rows:
        raise BcchFxSourceError("NO_ELIGIBLE_OBSERVATIONS", "Banco Central de Chile returned no eligible USD/CLP observations")

    accepted_dates = [row["bar_start"].astimezone(SANTIAGO).date() for row in rows]
    status_identity = {
        "policy_version": POLICY_VERSION,
        "provider": PROVIDER,
        "series_id": series_id,
        "start_date": start_date,
        "end_date": end_date,
        "ingestion_run_id": ingestion_run_id,
    }
    status = {
        "status_id": "fx_reference_status_" + sha256_json(status_identity),
        **status_identity,
        "ticker": str(ticker).strip().upper(),
        "base_currency": "USD",
        "quote_currency": "CLP",
        "status": "AVAILABLE",
        "authentication_mode": "API_TOKEN",
        "token_persisted": False,
        "response_observation_count": len(observations),
        "accepted_row_count": len(rows),
        "skipped_status_count": sum(skipped_statuses.values()),
        "skipped_status_counts": dict(sorted(skipped_statuses.items())),
        "first_rate_date": min(accepted_dates),
        "last_rate_date": max(accepted_dates),
        "availability_policy": AVAILABILITY_POLICY,
        "source_version": SOURCE_VERSION,
        "observed_at": ingested_at.astimezone(UTC),
        "production_change_allowed": False,
    }
    return rows, status

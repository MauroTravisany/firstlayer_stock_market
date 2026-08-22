"""Official Banco Central de Chile USD/CLP point-in-time source for WP-04."""

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
AVAILABILITY_POLICY = "bcch-previous-banking-day-1730-america-santiago-v1"
SOURCE_VERSION = "bcch-bde-rest-v1"
PROVIDER = "BCCH_BDE"
SERIES_ID = "F073.TCO.PRE.Z.D"
ENDPOINT = "https://si3.bcentral.cl/SieteRestWS/SieteRestWS.ashx"
SOURCE_TIMEZONE = "America/Santiago"
QUALITY_STATUS = "OFFICIAL_PUBLISHED_RATE"
QUERY_LOOKBACK_DAYS = 32
UTC = dt.timezone.utc
SANTIAGO = ZoneInfo(SOURCE_TIMEZONE)


class OfficialFxSourceError(RuntimeError):
    """An official FX response could not satisfy the fail-closed contract."""

    def __init__(self, reason_code: str, message: str):
        self.provider = PROVIDER
        self.reason_code = str(reason_code).strip().upper()
        super().__init__(str(message).strip())


def _parse_date(value: Any) -> dt.date:
    try:
        return dt.datetime.strptime(str(value or "").strip(), "%d-%m-%Y").date()
    except ValueError as exc:
        raise OfficialFxSourceError(
            "INVALID_OBSERVATION_DATE", "BCCh returned an invalid observation date"
        ) from exc


def _parse_rate(value: Any) -> float:
    text = str(value or "").strip()
    if not text:
        raise OfficialFxSourceError(
            "MISSING_OBSERVATION_VALUE", "BCCh returned a missing observation value"
        )
    if text.lower() in {"nd", "nan", "na", "n/a"}:
        raise OfficialFxSourceError(
            "NON_ELIGIBLE_OBSERVATION", "BCCh returned a non-eligible observation value"
        )
    normalized = (
        text.replace(".", "").replace(",", ".")
        if "," in text and "." in text
        else text.replace(",", ".")
    )
    try:
        parsed = float(Decimal(normalized))
    except (InvalidOperation, ValueError) as exc:
        raise OfficialFxSourceError(
            "NON_NUMERIC_OBSERVATION", "BCCh returned a non-numeric observation value"
        ) from exc
    if not math.isfinite(parsed) or parsed <= 0:
        raise OfficialFxSourceError(
            "INVALID_OBSERVATION_VALUE", "BCCh returned a non-positive or non-finite rate"
        )
    return parsed


def _response_json(response: Any) -> Mapping[str, Any]:
    try:
        document = response.json()
    except (TypeError, ValueError) as exc:
        raise OfficialFxSourceError("INVALID_JSON_RESPONSE", "BCCh returned invalid JSON") from exc
    if not isinstance(document, Mapping):
        raise OfficialFxSourceError(
            "INVALID_RESPONSE_SHAPE", "BCCh response root must be an object"
        )
    return document


def _published_at(reference_date: dt.date) -> dt.datetime:
    local = dt.datetime.combine(reference_date, dt.time(17, 30), tzinfo=SANTIAGO)
    return local.astimezone(UTC)


def _raw_row(
    *,
    rate_date: dt.date,
    source_reference_date: dt.date,
    rate: float,
    ingestion_run_id: str,
    ingested_at: dt.datetime,
) -> dict[str, Any]:
    source_published_at = _published_at(source_reference_date)
    local_rate_start = dt.datetime.combine(rate_date, dt.time.min, tzinfo=SANTIAGO)
    if source_reference_date >= rate_date or source_published_at >= local_rate_start.astimezone(UTC):
        raise OfficialFxSourceError(
            "INVALID_AVAILABILITY_LINEAGE", "BCCh publication lineage is not prior to rate_date"
        )
    ingested_at = ingested_at.astimezone(UTC)
    if source_published_at > ingested_at:
        raise OfficialFxSourceError(
            "AVAILABLE_AFTER_INGESTION", "BCCh observation availability cannot follow ingestion"
        )
    source_record_id = f"{SERIES_ID}:{rate_date.isoformat()}"
    payload = {
        "provider": PROVIDER,
        "series_id": SERIES_ID,
        "rate_date": rate_date,
        "source_reference_date": source_reference_date,
        "rate": rate,
        "status_code": "OK",
    }
    payload_hash = sha256_json(payload)
    record_identity = {"provider": PROVIDER, "series_id": SERIES_ID, "rate_date": rate_date}
    revision_identity = {
        **record_identity,
        "payload_hash": payload_hash,
        "source_published_at": source_published_at,
    }
    return {
        "fx_rate_revision_id": "fx_rate_revision_" + sha256_json(revision_identity),
        "fx_rate_record_id": "fx_rate_" + sha256_json(record_identity),
        "ingestion_run_id": ingestion_run_id,
        "provider": PROVIDER,
        "series_id": SERIES_ID,
        "rate_date": rate_date,
        "source_reference_date": source_reference_date,
        "base_currency": "USD",
        "quote_currency": "CLP",
        "rate": rate,
        "status_code": "OK",
        "source_record_id": source_record_id,
        "source_version": SOURCE_VERSION,
        "source_timezone": SOURCE_TIMEZONE,
        "source_published_at": source_published_at,
        "availability_policy": AVAILABILITY_POLICY,
        "payload_hash": payload_hash,
        "available_at": source_published_at,
        "ingested_at": ingested_at,
        "quality_status": QUALITY_STATUS,
        "production_change_allowed": False,
    }


def fetch_bcch_observed_dollar(
    *,
    token: str | None,
    start_date: dt.date,
    end_date: dt.date,
    ingestion_run_id: str,
    ingested_at: dt.datetime,
    timeout_seconds: int = 30,
    get: Callable[..., Any] = requests.get,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fetch the official series and return raw rows plus sanitized status."""

    secret = str(token or "").strip()
    if not secret:
        raise OfficialFxSourceError("AUTHENTICATION_MISSING", "BCCH_API_TOKEN is required")
    if end_date < start_date:
        raise OfficialFxSourceError("INVALID_DATE_RANGE", "end_date precedes start_date")
    if not str(ingestion_run_id or "").strip():
        raise OfficialFxSourceError("INGESTION_RUN_ID_MISSING", "ingestion_run_id is required")
    if ingested_at.tzinfo is None or ingested_at.utcoffset() is None:
        raise OfficialFxSourceError("INVALID_INGESTION_TIME", "ingested_at must be timezone-aware")

    query_start = start_date - dt.timedelta(days=QUERY_LOOKBACK_DAYS)
    try:
        response = get(
            ENDPOINT,
            params={
                "token": secret,
                "function": "GetSeries",
                "timeseries": SERIES_ID,
                "firstdate": query_start.isoformat(),
                "lastdate": end_date.isoformat(),
            },
            timeout=int(timeout_seconds),
            headers={"Accept": "application/json", "User-Agent": "FirstLayerStockMarket-WP04/4.0"},
        )
    except requests.RequestException as exc:
        raise OfficialFxSourceError("NETWORK_ERROR", "BCCh request failed") from exc

    status_code = int(getattr(response, "status_code", 0) or 0)
    if status_code in {401, 403}:
        raise OfficialFxSourceError("AUTHENTICATION_FAILED", "BCCh rejected the API token")
    if status_code == 429:
        raise OfficialFxSourceError("RATE_LIMITED", "BCCh rate limited the request")
    if not 200 <= status_code < 300:
        raise OfficialFxSourceError("HTTP_ERROR", f"BCCh returned HTTP {status_code}")

    document = _response_json(response)
    try:
        api_code = int(document.get("Codigo"))
    except (TypeError, ValueError) as exc:
        raise OfficialFxSourceError("INVALID_RESPONSE_CODE", "BCCh response code is invalid") from exc
    if api_code != 0:
        raise OfficialFxSourceError("API_NON_SUCCESS", "BCCh returned a non-success response")
    series = document.get("Series")
    if not isinstance(series, Mapping) or str(series.get("seriesId") or "").strip() != SERIES_ID:
        raise OfficialFxSourceError("SERIES_MISMATCH", "BCCh returned an unexpected series")
    observations = series.get("Obs")
    if not isinstance(observations, list):
        raise OfficialFxSourceError("OBSERVATIONS_MISSING", "BCCh response is missing Series.Obs")

    parsed: list[tuple[dt.date, float]] = []
    seen_dates: set[dt.date] = set()
    skipped: Counter[str] = Counter()
    for observation in observations:
        if not isinstance(observation, Mapping):
            raise OfficialFxSourceError(
                "INVALID_OBSERVATION_SHAPE", "BCCh observation must be an object"
            )
        day = _parse_date(observation.get("indexDateString"))
        if day in seen_dates:
            raise OfficialFxSourceError(
                "DUPLICATE_OBSERVATION_DATE", "BCCh returned a duplicate observation date"
            )
        seen_dates.add(day)
        observation_status = str(observation.get("statusCode") or "").strip().upper()
        if observation_status != "OK":
            skipped[observation_status or "MISSING_STATUS"] += 1
            continue
        try:
            rate = _parse_rate(observation.get("value"))
        except OfficialFxSourceError as exc:
            if exc.reason_code == "NON_ELIGIBLE_OBSERVATION":
                skipped[str(observation.get("value") or "MISSING_VALUE").strip().upper()] += 1
                continue
            raise
        parsed.append((day, rate))

    parsed.sort(key=lambda item: item[0])
    rows: list[dict[str, Any]] = []
    for index, (rate_date, rate) in enumerate(parsed):
        if not start_date <= rate_date <= end_date:
            continue
        if index == 0:
            raise OfficialFxSourceError(
                "PRIOR_OBSERVATION_MISSING",
                "first requested BCCh observation has no prior OK observation",
            )
        rows.append(
            _raw_row(
                rate_date=rate_date,
                source_reference_date=parsed[index - 1][0],
                rate=rate,
                ingestion_run_id=ingestion_run_id,
                ingested_at=ingested_at,
            )
        )
    if not rows:
        raise OfficialFxSourceError(
            "NO_ELIGIBLE_OBSERVATIONS", "BCCh returned no eligible observations in the requested range"
        )
    revision_ids = [row["fx_rate_revision_id"] for row in rows]
    if len(revision_ids) != len(set(revision_ids)):
        raise OfficialFxSourceError(
            "DUPLICATE_REVISION_ID", "BCCh normalization produced duplicate revision IDs"
        )

    status_identity = {
        "policy_version": POLICY_VERSION,
        "provider": PROVIDER,
        "series_id": SERIES_ID,
        "query_start_date": query_start,
        "start_date": start_date,
        "end_date": end_date,
        "ingestion_run_id": ingestion_run_id,
    }
    status = {
        "status_id": "official_fx_status_" + sha256_json(status_identity),
        **status_identity,
        "required": True,
        "authentication_mode": "API_KEY",
        "accepted_row_count": len(rows),
        "skipped_status_counts": dict(sorted(skipped.items())),
        "source_version": SOURCE_VERSION,
        "availability_policy": AVAILABILITY_POLICY,
        "observed_at": ingested_at.astimezone(UTC),
        "production_change_allowed": False,
    }
    return rows, status

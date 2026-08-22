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


SOURCE_POLICY_VERSION = "wp04-bcch-observed-dollar-v1"
POLICY_VERSION = "wp04-bcch-vintage-availability-v2"
AVAILABILITY_POLICY = POLICY_VERSION
SOURCE_VERSION = "bcch-bde-rest-v1"
PROVIDER = "BCCH_BDE"
SERIES_ID = "F073.TCO.PRE.Z.D"
ENDPOINT = "https://si3.bcentral.cl/SieteRestWS/SieteRestWS.ashx"
SOURCE_TIMEZONE = "America/Santiago"
QUALITY_STATUS = "CURRENT_SNAPSHOT_NO_VINTAGE"
QUERY_LOOKBACK_DAYS = 32
UTC = dt.timezone.utc
SANTIAGO = ZoneInfo(SOURCE_TIMEZONE)


class OfficialFxSourceError(RuntimeError):
    """An official FX response could not satisfy the fail-closed contract."""

    def __init__(self, reason_code: str, message: str):
        self.provider = PROVIDER
        self.reason_code = str(reason_code).strip().upper()
        super().__init__(str(message).strip())


def utc_now() -> dt.datetime:
    """Return the current timezone-aware UTC instant."""

    return dt.datetime.now(UTC)


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
    except (TypeError, ValueError):
        raise OfficialFxSourceError("INVALID_JSON_RESPONSE", "BCCh returned invalid JSON") from None
    if not isinstance(document, Mapping):
        raise OfficialFxSourceError(
            "INVALID_RESPONSE_SHAPE", "BCCh response root must be an object"
        )
    return document


def _published_at(reference_date: dt.date) -> dt.datetime:
    local = dt.datetime.combine(reference_date, dt.time(17, 30), tzinfo=SANTIAGO)
    return local.astimezone(UTC)


def _as_date(value: Any, field: str) -> dt.date:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value))
    except (TypeError, ValueError):
        raise OfficialFxSourceError("INVALID_ROW", f"fx_rate_raw {field} is invalid") from None


def _as_datetime(value: Any, field: str) -> dt.datetime:
    if isinstance(value, dt.datetime):
        parsed = value
    else:
        try:
            parsed = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            raise OfficialFxSourceError(
                "INVALID_ROW", f"fx_rate_raw {field} is invalid"
            ) from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise OfficialFxSourceError("INVALID_ROW", f"fx_rate_raw {field} must be timezone-aware")
    return parsed.astimezone(UTC)


def _identities(
    *,
    rate_date: dt.date,
    source_reference_date: dt.date,
    rate: float,
    source_published_at: dt.datetime,
) -> tuple[str, str, str]:
    payload_hash = sha256_json(
        {
            "provider": PROVIDER,
            "series_id": SERIES_ID,
            "rate_date": rate_date,
            "source_reference_date": source_reference_date,
            "rate": rate,
            "status_code": "OK",
        }
    )
    record_identity = {"provider": PROVIDER, "series_id": SERIES_ID, "rate_date": rate_date}
    revision_identity = {
        **record_identity,
        "payload_hash": payload_hash,
        "source_published_at": source_published_at,
    }
    return (
        payload_hash,
        "fx_rate_" + sha256_json(record_identity),
        "fx_rate_revision_" + sha256_json(revision_identity),
    )


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
    payload_hash, record_id, revision_id = _identities(
        rate_date=rate_date,
        source_reference_date=source_reference_date,
        rate=rate,
        source_published_at=source_published_at,
    )
    first_observed_at = ingested_at
    return {
        "fx_rate_revision_id": revision_id,
        "fx_rate_record_id": record_id,
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
        "first_observed_at": first_observed_at,
        "publication_evidence_uri": None,
        "publication_evidence_sha256": None,
        "publication_evidence_at": None,
        "available_at": first_observed_at,
        "ingested_at": ingested_at,
        "quality_status": QUALITY_STATUS,
        "backtest_eligible": False,
        "production_change_allowed": False,
    }


def validate_official_fx_row(
    row: Mapping[str, Any],
    *,
    expected_ingestion_run_id: str | None = None,
    expected_observed_at: Any | None = None,
) -> None:
    """Recompute every security-relevant field in one current-snapshot row."""

    required = {
        "fx_rate_revision_id", "fx_rate_record_id", "ingestion_run_id", "provider",
        "series_id", "rate_date", "source_reference_date", "base_currency",
        "quote_currency", "rate", "status_code", "source_record_id", "source_version",
        "source_timezone", "source_published_at", "availability_policy", "payload_hash",
        "first_observed_at", "publication_evidence_uri", "publication_evidence_sha256",
        "publication_evidence_at", "available_at", "ingested_at", "quality_status",
        "backtest_eligible", "production_change_allowed",
    }
    if set(row) != required:
        raise OfficialFxSourceError("INVALID_ROW", "fx_rate_raw columns do not match contract")
    constants = {
        "provider": PROVIDER,
        "series_id": SERIES_ID,
        "base_currency": "USD",
        "quote_currency": "CLP",
        "status_code": "OK",
        "source_version": SOURCE_VERSION,
        "source_timezone": SOURCE_TIMEZONE,
        "availability_policy": AVAILABILITY_POLICY,
        "quality_status": QUALITY_STATUS,
        "backtest_eligible": False,
        "production_change_allowed": False,
    }
    if any(row.get(key) != value for key, value in constants.items()):
        raise OfficialFxSourceError("INVALID_ROW", "fx_rate_raw constant field is invalid")
    if any(row.get(key) is not None for key in (
        "publication_evidence_uri", "publication_evidence_sha256", "publication_evidence_at"
    )):
        raise OfficialFxSourceError(
            "INVALID_ROW", "current API snapshot cannot claim publication vintage evidence"
        )
    if isinstance(row["rate"], bool):
        raise OfficialFxSourceError("INVALID_ROW", "fx_rate_raw rate is invalid")
    try:
        rate = float(row["rate"])
    except (TypeError, ValueError):
        raise OfficialFxSourceError("INVALID_ROW", "fx_rate_raw rate is invalid") from None
    if not math.isfinite(rate) or rate <= 0:
        raise OfficialFxSourceError("INVALID_ROW", "fx_rate_raw rate must be finite and positive")
    rate_date = _as_date(row["rate_date"], "rate_date")
    reference_date = _as_date(row["source_reference_date"], "source_reference_date")
    published = _as_datetime(row["source_published_at"], "source_published_at")
    first_observed = _as_datetime(row["first_observed_at"], "first_observed_at")
    available = _as_datetime(row["available_at"], "available_at")
    ingested = _as_datetime(row["ingested_at"], "ingested_at")
    expected_published = _published_at(reference_date)
    if reference_date >= rate_date or published != expected_published:
        raise OfficialFxSourceError("INVALID_ROW", "fx_rate_raw publication lineage is invalid")
    if published >= dt.datetime.combine(rate_date, dt.time.min, tzinfo=SANTIAGO).astimezone(UTC):
        raise OfficialFxSourceError("INVALID_ROW", "fx_rate_raw publication is not prior")
    if published > first_observed:
        raise OfficialFxSourceError(
            "INVALID_ROW", "fx_rate_raw publication follows first observation"
        )
    if first_observed != ingested or available != first_observed:
        raise OfficialFxSourceError("INVALID_ROW", "fx_rate_raw vintage availability order is invalid")
    payload_hash, record_id, revision_id = _identities(
        rate_date=rate_date,
        source_reference_date=reference_date,
        rate=rate,
        source_published_at=published,
    )
    expected = {
        "payload_hash": payload_hash,
        "fx_rate_record_id": record_id,
        "fx_rate_revision_id": revision_id,
        "source_record_id": f"{SERIES_ID}:{rate_date.isoformat()}",
    }
    if any(row.get(key) != value for key, value in expected.items()):
        raise OfficialFxSourceError("INVALID_ROW", "fx_rate_raw content identity is invalid")
    ingestion_run_id = str(row.get("ingestion_run_id") or "").strip()
    if not ingestion_run_id:
        raise OfficialFxSourceError("INVALID_ROW", "fx_rate_raw ingestion_run_id is missing")
    if (
        expected_ingestion_run_id is not None
        and ingestion_run_id != str(expected_ingestion_run_id).strip()
    ):
        raise OfficialFxSourceError(
            "INVALID_ROW", "fx_rate_raw ingestion_run_id does not match source status"
        )
    if (
        expected_observed_at is not None
        and ingested != _as_datetime(expected_observed_at, "observed_at")
    ):
        raise OfficialFxSourceError(
            "INVALID_ROW", "fx_rate_raw ingestion time does not match source status"
        )


def official_source_policy() -> dict[str, Any]:
    return {
        "policy_version": POLICY_VERSION,
        "source_policy_version": SOURCE_POLICY_VERSION,
        "provider": PROVIDER,
        "series_id": SERIES_ID,
        "source_version": SOURCE_VERSION,
        "required": True,
        "source_role": "OFFICIAL_SCALAR_RATE",
        "yahoo_fx_role": "DIAGNOSTIC_ONLY",
        "availability_policy": AVAILABILITY_POLICY,
        "vintage_evidence_mode": "CURRENT_SNAPSHOT_NO_ARCHIVE",
        "production_change_allowed": False,
    }


def build_status_document(
    *, query_start_date: dt.date, start_date: dt.date, end_date: dt.date,
    ingestion_run_id: str, accepted_row_count: int, skipped_status_counts: Mapping[str, int],
    observed_at: dt.datetime,
) -> dict[str, Any]:
    document = {
        "policy_version": POLICY_VERSION,
        "provider": PROVIDER,
        "series_id": SERIES_ID,
        "query_start_date": query_start_date,
        "start_date": start_date,
        "end_date": end_date,
        "ingestion_run_id": ingestion_run_id,
        "required": True,
        "authentication_mode": "API_KEY",
        "accepted_row_count": int(accepted_row_count),
        "skipped_status_counts": dict(sorted(skipped_status_counts.items())),
        "source_version": SOURCE_VERSION,
        "availability_policy": AVAILABILITY_POLICY,
        "observed_at": observed_at.astimezone(UTC),
        "production_change_allowed": False,
    }
    return {
        "status_id": "official_fx_status_" + sha256_json(document),
        **document,
    }


def validate_official_fx_status(status: Mapping[str, Any], *, row_count: int) -> None:
    expected_keys = {
        "status_id", "policy_version", "provider", "series_id", "query_start_date",
        "start_date", "end_date", "ingestion_run_id", "required", "authentication_mode",
        "accepted_row_count", "skipped_status_counts", "source_version",
        "availability_policy", "observed_at", "production_change_allowed",
    }
    if set(status) != expected_keys:
        raise OfficialFxSourceError("INVALID_STATUS", "official FX status columns are invalid")
    constants = {
        "policy_version": POLICY_VERSION, "provider": PROVIDER, "series_id": SERIES_ID,
        "required": True, "authentication_mode": "API_KEY", "source_version": SOURCE_VERSION,
        "availability_policy": AVAILABILITY_POLICY, "production_change_allowed": False,
    }
    if any(status.get(key) != value for key, value in constants.items()):
        raise OfficialFxSourceError("INVALID_STATUS", "official FX status contract is invalid")
    accepted = status.get("accepted_row_count")
    if isinstance(accepted, bool) or not isinstance(accepted, int) or accepted != row_count:
        raise OfficialFxSourceError("INVALID_STATUS", "official FX status row count is invalid")
    skipped = status.get("skipped_status_counts")
    if not isinstance(skipped, Mapping) or any(
        not isinstance(key, str)
        or not key.strip()
        or key != key.strip().upper()
        or isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        for key, value in skipped.items()
    ):
        raise OfficialFxSourceError(
            "INVALID_STATUS", "official FX skipped status counts are invalid"
        )
    query_start = _as_date(status["query_start_date"], "query_start_date")
    start = _as_date(status["start_date"], "start_date")
    end = _as_date(status["end_date"], "end_date")
    observed = _as_datetime(status["observed_at"], "observed_at")
    if (
        query_start != start - dt.timedelta(days=QUERY_LOOKBACK_DAYS)
        or start > end
        or not str(status.get("ingestion_run_id") or "").strip()
    ):
        raise OfficialFxSourceError("INVALID_STATUS", "official FX status range is invalid")
    rebuilt = build_status_document(
        query_start_date=query_start, start_date=start, end_date=end,
        ingestion_run_id=str(status["ingestion_run_id"]),
        accepted_row_count=row_count,
        skipped_status_counts=skipped,
        observed_at=observed,
    )
    if status.get("status_id") != rebuilt["status_id"]:
        raise OfficialFxSourceError("INVALID_STATUS", "official FX status identity is invalid")


def select_revision_as_of(
    rows: list[Mapping[str, Any]], signal_timestamp: dt.datetime
) -> Mapping[str, Any] | None:
    """Select the deterministic revision visible at a signal timestamp."""
    signal = _as_datetime(signal_timestamp, "signal_timestamp")
    eligible = [row for row in rows if _as_datetime(row["available_at"], "available_at") <= signal]
    if not eligible:
        return None
    return max(
        eligible,
        key=lambda row: (
            _as_datetime(row["available_at"], "available_at"),
            _as_datetime(row["ingested_at"], "ingested_at"),
            str(row["fx_rate_revision_id"]),
        ),
    )


def fetch_bcch_observed_dollar(
    *,
    token: str | None,
    start_date: dt.date,
    end_date: dt.date,
    ingestion_run_id: str,
    timeout_seconds: int = 30,
    get: Callable[..., Any] = requests.get,
    clock: Callable[[], dt.datetime] = utc_now,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fetch the official series and return raw rows plus sanitized status."""

    secret = str(token or "").strip()
    if not secret:
        raise OfficialFxSourceError("AUTHENTICATION_MISSING", "BCCH_API_TOKEN is required")
    if end_date < start_date:
        raise OfficialFxSourceError("INVALID_DATE_RANGE", "end_date precedes start_date")
    if not str(ingestion_run_id or "").strip():
        raise OfficialFxSourceError("INGESTION_RUN_ID_MISSING", "ingestion_run_id is required")

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
    except requests.RequestException:
        raise OfficialFxSourceError("NETWORK_ERROR", "BCCh request failed") from None

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

    observed_at = clock()
    if (
        not isinstance(observed_at, dt.datetime)
        or observed_at.tzinfo is None
        or observed_at.utcoffset() is None
    ):
        raise OfficialFxSourceError(
            "INVALID_OBSERVATION_TIME", "BCCh observation clock must be timezone-aware"
        )
    observed_at = observed_at.astimezone(UTC)

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
                ingested_at=observed_at,
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

    status = build_status_document(
        query_start_date=query_start,
        start_date=start_date,
        end_date=end_date,
        ingestion_run_id=ingestion_run_id,
        accepted_row_count=len(rows),
        skipped_status_counts=skipped,
        observed_at=observed_at,
    )
    return rows, status

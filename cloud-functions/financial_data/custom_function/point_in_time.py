import hashlib
import json
import re
from datetime import datetime, timezone


CORE_FINANCIAL_FACTS = {
    "revenue",
    "net_income",
    "eps_basic",
    "eps_diluted",
    "total_assets",
    "shareholders_equity",
}
DERIVED_IDENTITY_FIELDS = {
    "revision_id",
    "revision_number",
    "is_restated",
    "backtest_eligible",
    "eligibility_reason",
    "quality_status",
    "loaded_at",
}


def canonical_json(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, default=str)


def content_hash(value):
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def normalize_timestamp(value):
    if value is None:
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if re.fullmatch(r"\d{14}", text):
            dt = datetime.strptime(text, "%Y%m%d%H%M%S").replace(tzinfo=timezone.utc)
        else:
            text = text.replace("Z", "+00:00")
            dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _fiscal_metadata_valid(form_type, fiscal_year, fiscal_quarter):
    if fiscal_year is None:
        return False
    normalized = str(form_type or "").upper()
    if normalized.startswith("10-Q"):
        return fiscal_quarter in {1, 2, 3}
    if normalized.startswith(("10-K", "20-F", "40-F")):
        return fiscal_quarter == 4
    return False


def refresh_revision_identity(payload):
    immutable_basis = {
        key: value
        for key, value in payload.items()
        if key not in DERIVED_IDENTITY_FIELDS
    }
    payload["revision_id"] = content_hash(immutable_basis)
    return payload


def build_statement_revision(
    *,
    ticker,
    cik,
    form_type,
    accession_number,
    filing_date,
    source_published_at,
    period_end_date,
    fiscal_year,
    fiscal_quarter,
    currency,
    facts,
    source_url,
    mapping_version,
    source="SEC_EDGAR",
):
    available_at = normalize_timestamp(source_published_at)
    normalized_form = str(form_type or "").upper()
    normalized_year = int(fiscal_year) if fiscal_year is not None else None
    normalized_quarter = int(fiscal_quarter) if fiscal_quarter is not None else None
    fiscal_metadata_valid = _fiscal_metadata_valid(
        normalized_form, normalized_year, normalized_quarter
    )
    has_usable_fact = any(
        facts.get(field) is not None for field in CORE_FINANCIAL_FACTS
    )
    payload = {
        "ticker": ticker.upper(),
        "cik": str(cik).zfill(10),
        "mapping_version": str(mapping_version),
        "form_type": normalized_form,
        "accession_number": accession_number,
        "source_record_id": accession_number,
        "revision_number": None,
        "is_restated": normalized_form.endswith("/A"),
        "filing_date": str(filing_date) if filing_date is not None else None,
        "source_published_at": available_at,
        "available_at": available_at,
        "period_end_date": str(period_end_date) if period_end_date is not None else None,
        "fiscal_year": normalized_year,
        "fiscal_quarter": normalized_quarter,
        "currency": currency,
        "source": source,
        "source_url": source_url,
        **facts,
    }
    evidence_complete = bool(
        available_at and accession_number and source_url and period_end_date
    )
    payload["backtest_eligible"] = bool(
        evidence_complete and fiscal_metadata_valid and has_usable_fact
    )
    if not evidence_complete:
        reason = "MISSING_VERIFIABLE_AVAILABILITY"
        quality_status = "UNVERIFIED_AVAILABLE_AT"
    elif not fiscal_metadata_valid:
        reason = "MISSING_VERIFIABLE_FISCAL_PERIOD"
        quality_status = "UNVERIFIED_FISCAL_PERIOD"
    elif not has_usable_fact:
        reason = "MISSING_USABLE_FINANCIAL_FACTS"
        quality_status = "NO_USABLE_FINANCIAL_FACTS"
    else:
        reason = "VERIFIED_SOURCE_AVAILABILITY_AND_FISCAL_METADATA"
        quality_status = "ELIGIBLE_VERIFIED_PIT"
    payload["eligibility_reason"] = reason
    payload["quality_status"] = quality_status
    payload["loaded_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return refresh_revision_identity(payload)


def _revision_rank(row):
    return (
        str(row.get("period_end_date") or ""),
        normalize_timestamp(row.get("available_at")) or "",
        int(row.get("revision_number") or 0),
        str(row.get("revision_id") or ""),
    )


def select_as_of(revisions, as_of):
    cutoff = normalize_timestamp(as_of)
    eligible = [
        row
        for row in revisions
        if row.get("backtest_eligible")
        and row.get("available_at")
        and normalize_timestamp(row["available_at"]) <= cutoff
    ]
    if not eligible:
        return None
    return max(eligible, key=_revision_rank)


def compute_quarterly_yoy(rows, value_field):
    by_key = {}
    for row in rows:
        fiscal_year = row.get("fiscal_year")
        fiscal_quarter = row.get("fiscal_quarter")
        if fiscal_year is None or fiscal_quarter not in {1, 2, 3, 4}:
            continue
        key = (int(fiscal_year), int(fiscal_quarter))
        if key not in by_key or _revision_rank(row) > _revision_rank(by_key[key]):
            by_key[key] = row

    result = []
    for row in rows:
        current = row.get(value_field)
        quarter = row.get("fiscal_quarter")
        fiscal_year = row.get("fiscal_year")
        prior = (
            by_key.get((int(fiscal_year) - 1, int(quarter)))
            if fiscal_year is not None and quarter is not None
            else None
        )
        prior_value = prior.get(value_field) if prior else None
        yoy = None
        if current is not None and prior_value not in (None, 0):
            yoy = (float(current) - float(prior_value)) / abs(float(prior_value))
        result.append({**row, f"{value_field}_yoy": yoy})
    return result

import hashlib
import json
from datetime import datetime, timezone


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
        text = str(value).strip().replace("Z", "+00:00")
        dt = datetime.fromisoformat(text)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def build_statement_revision(*, ticker, cik, form_type, accession_number, filing_date,
                             source_published_at, period_end_date, fiscal_year,
                             fiscal_quarter, currency, facts, source_url,
                             source="SEC_EDGAR"):
    available_at = normalize_timestamp(source_published_at)
    payload = {
        "ticker": ticker.upper(),
        "cik": str(cik).zfill(10),
        "form_type": form_type,
        "accession_number": accession_number,
        "filing_date": str(filing_date),
        "source_published_at": available_at,
        "available_at": available_at,
        "period_end_date": str(period_end_date),
        "fiscal_year": int(fiscal_year),
        "fiscal_quarter": int(fiscal_quarter) if fiscal_quarter is not None else None,
        "currency": currency,
        "source": source,
        "source_url": source_url,
        **facts,
    }
    payload["backtest_eligible"] = bool(available_at and accession_number and source_url)
    payload["eligibility_reason"] = (
        "VERIFIED_SOURCE_AVAILABILITY"
        if payload["backtest_eligible"]
        else "MISSING_VERIFIABLE_AVAILABILITY"
    )
    immutable_basis = {k: v for k, v in payload.items() if k not in {"revision_id", "loaded_at"}}
    payload["revision_id"] = content_hash(immutable_basis)
    payload["loaded_at"] = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    return payload


def select_as_of(revisions, as_of):
    cutoff = normalize_timestamp(as_of)
    eligible = [
        row for row in revisions
        if row.get("backtest_eligible")
        and row.get("available_at")
        and normalize_timestamp(row["available_at"]) <= cutoff
    ]
    if not eligible:
        return None
    return max(eligible, key=lambda row: (normalize_timestamp(row["available_at"]), row["revision_id"]))


def compute_quarterly_yoy(rows, value_field):
    by_key = {
        (int(row["fiscal_year"]), int(row["fiscal_quarter"])): row
        for row in rows
        if row.get("fiscal_quarter") is not None
    }
    result = []
    for row in rows:
        current = row.get(value_field)
        quarter = row.get("fiscal_quarter")
        prior = by_key.get((int(row["fiscal_year"]) - 1, int(quarter))) if quarter is not None else None
        prior_value = prior.get(value_field) if prior else None
        yoy = None
        if current is not None and prior_value not in (None, 0):
            yoy = (float(current) - float(prior_value)) / abs(float(prior_value))
        result.append({**row, f"{value_field}_yoy": yoy})
    return result

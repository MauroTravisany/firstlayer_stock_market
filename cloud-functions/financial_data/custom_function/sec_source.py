import os
import re
from datetime import date

import requests

from .point_in_time import build_statement_revision

SEC_DATA_BASE = "https://data.sec.gov"
SEC_FORMS = {"10-Q", "10-Q/A", "10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}
DURATION_FACTS = {
    "revenue",
    "gross_profit",
    "operating_income",
    "net_income",
    "eps_basic",
    "eps_diluted",
    "operating_cash_flow",
}


def _headers():
    user_agent = os.environ.get("SEC_USER_AGENT", "")
    if not user_agent or "@" not in user_agent:
        raise RuntimeError("SEC_USER_AGENT must identify the application and include a contact email")
    return {"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate", "Accept": "application/json"}


def _get_json(url, timeout=30):
    response = requests.get(url, headers=_headers(), timeout=timeout)
    response.raise_for_status()
    return response.json()


def normalize_cik(cik):
    digits = re.sub(r"\D", "", str(cik))
    if not digits:
        raise ValueError("CIK is required")
    return digits.zfill(10)


def fetch_submissions(cik):
    """Fetch current and referenced historical submission files from SEC EDGAR."""
    cik10 = normalize_cik(cik)
    document = _get_json(f"{SEC_DATA_BASE}/submissions/CIK{cik10}.json")
    supplemental = []
    for descriptor in (document.get("filings") or {}).get("files") or []:
        name = descriptor.get("name")
        if not name:
            continue
        payload = _get_json(f"{SEC_DATA_BASE}/submissions/{name}")
        if isinstance(payload, dict):
            supplemental.append(payload)
    document["_supplemental_filings"] = supplemental
    return document


def fetch_companyfacts(cik):
    cik10 = normalize_cik(cik)
    return _get_json(f"{SEC_DATA_BASE}/api/xbrl/companyfacts/CIK{cik10}.json")


def _filing_documents(submissions):
    filings = submissions.get("filings") or {}
    documents = list(submissions.get("_supplemental_filings") or [])
    recent = filings.get("recent") or {}
    if recent:
        documents.append(recent)
    return documents


def recent_filings_by_accession(submissions):
    """Normalize current + historical SEC submission arrays keyed by accession."""
    rows = {}
    for document in _filing_documents(submissions):
        accessions = document.get("accessionNumber") or []
        for index, accession in enumerate(accessions):
            def value(name):
                values = document.get(name) or []
                return values[index] if index < len(values) else None

            form = value("form")
            if form not in SEC_FORMS:
                continue
            rows[accession] = {
                "accession_number": accession,
                "form_type": form,
                "filing_date": value("filingDate"),
                "source_published_at": value("acceptanceDateTime"),
                "period_end_date": value("reportDate"),
                "primary_document": value("primaryDocument"),
            }
    return rows


def _matching_fact_rows(companyfacts, concepts, *, accession, period_end, unit_preferences):
    facts = companyfacts.get("facts") or {}
    for taxonomy in ("us-gaap", "ifrs-full", "dei"):
        namespace = facts.get(taxonomy) or {}
        for concept in concepts:
            units = (namespace.get(concept) or {}).get("units") or {}
            for unit in unit_preferences:
                for row in units.get(unit) or []:
                    if row.get("accn") == accession and (not period_end or row.get("end") == period_end):
                        yield row, unit


def _duration_days(row):
    start = row.get("start")
    end = row.get("end")
    if not start or not end:
        return None
    try:
        return (date.fromisoformat(end) - date.fromisoformat(start)).days
    except ValueError:
        return None


def _target_duration(form_type, fiscal_quarter):
    normalized = str(form_type or "").upper()
    if normalized.startswith(("10-K", "20-F", "40-F")) or fiscal_quarter == 4:
        return 365
    if normalized.startswith("10-Q") and fiscal_quarter in {1, 2, 3}:
        return 91
    return None


def _choose_fact(companyfacts, concepts, *, accession, period_end, unit_preferences,
                 duration_target=None, require_duration=False):
    matches = list(_matching_fact_rows(
        companyfacts, concepts, accession=accession, period_end=period_end,
        unit_preferences=unit_preferences,
    ))
    if require_duration:
        matches = [pair for pair in matches if _duration_days(pair[0]) is not None]
    if not matches:
        return None, None, None

    def rank(pair):
        row, _unit = pair
        duration = _duration_days(row)
        duration_penalty = abs(duration - duration_target) if duration_target is not None and duration is not None else 10_000
        frame_bonus = 0 if row.get("frame") else 1
        return (
            duration_penalty,
            frame_bonus,
            -(int(str(row.get("fy") or 0))),
            str(row.get("filed") or ""),
        )

    if duration_target is not None:
        chosen, unit = min(matches, key=rank)
        duration = _duration_days(chosen)
        tolerance = 35 if duration_target == 91 else 75
        if duration is None or abs(duration - duration_target) > tolerance:
            return None, None, None
    else:
        chosen, unit = max(matches, key=lambda pair: (pair[0].get("filed") or "", pair[0].get("fy") or 0, pair[0].get("frame") or ""))
    return chosen.get("val"), unit, chosen


def _fiscal_metadata(companyfacts, accession, period_end):
    concepts = [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
        "NetIncomeLoss",
        "ProfitLoss",
    ]
    candidates = []
    for concept in concepts:
        for row, _unit in _matching_fact_rows(
            companyfacts, [concept], accession=accession, period_end=period_end,
            unit_preferences=["USD"],
        ):
            if row.get("fy") is not None and row.get("fp"):
                candidates.append(row)
    if not candidates:
        return None, None
    chosen = max(candidates, key=lambda row: (row.get("filed") or "", str(row.get("fp") or "")))
    fp = str(chosen.get("fp") or "").upper()
    quarter = {"Q1": 1, "Q2": 2, "Q3": 3, "FY": 4}.get(fp)
    return int(chosen["fy"]), quarter


def _debt_values(companyfacts, accession, period_end):
    kwargs = dict(accession=accession, period_end=period_end, unit_preferences=["USD"])
    total, _, _ = _choose_fact(companyfacts, ["LongTermDebtAndFinanceLeaseObligations", "DebtAndFinanceLeaseObligations"], **kwargs)
    current, _, _ = _choose_fact(companyfacts, ["LongTermDebtAndFinanceLeaseObligationsCurrent", "LongTermDebtCurrent", "DebtCurrent"], **kwargs)
    noncurrent, _, _ = _choose_fact(companyfacts, ["LongTermDebtAndFinanceLeaseObligationsNoncurrent", "LongTermDebtNoncurrent"], **kwargs)
    if total is None and (current is not None or noncurrent is not None):
        total = float(current or 0) + float(noncurrent or 0)
    return total, current, noncurrent


def build_sec_statement_revisions(ticker, cik, submissions, companyfacts):
    filings = recent_filings_by_accession(submissions)
    revisions = []
    mappings = {
        "revenue": (["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet"], ["USD"]),
        "gross_profit": (["GrossProfit"], ["USD"]),
        "operating_income": (["OperatingIncomeLoss"], ["USD"]),
        "net_income": (["NetIncomeLoss", "ProfitLoss"], ["USD"]),
        "eps_basic": (["EarningsPerShareBasic"], ["USD/shares", "USD / shares"]),
        "eps_diluted": (["EarningsPerShareDiluted"], ["USD/shares", "USD / shares"]),
        "total_assets": (["Assets"], ["USD"]),
        "total_liabilities": (["Liabilities"], ["USD"]),
        "shareholders_equity": (["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"], ["USD"]),
        "operating_cash_flow": (["NetCashProvidedByUsedInOperatingActivities"], ["USD"]),
        "cash_and_equivalents": (["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"], ["USD"]),
        "shares_outstanding": (["EntityCommonStockSharesOutstanding", "CommonStockSharesOutstanding"], ["shares"]),
    }
    cik10 = normalize_cik(cik)
    cik_numeric = str(int(cik10))
    for accession, filing in filings.items():
        period_end = filing.get("period_end_date")
        if not period_end:
            continue
        fiscal_year, fiscal_quarter = _fiscal_metadata(companyfacts, accession, period_end)
        duration_target = _target_duration(filing.get("form_type"), fiscal_quarter)
        facts = {}
        currency = None
        for field, (concepts, units) in mappings.items():
            is_duration = field in DURATION_FACTS
            value, unit, _metadata = _choose_fact(
                companyfacts,
                concepts,
                accession=accession,
                period_end=period_end,
                unit_preferences=units,
                duration_target=duration_target if is_duration else None,
                require_duration=is_duration,
            )
            facts[field] = value
            if field == "revenue" and unit == "USD":
                currency = "USD"
        total_debt, debt_current, debt_noncurrent = _debt_values(companyfacts, accession, period_end)
        facts["total_debt"] = total_debt
        facts["debt_current"] = debt_current
        facts["debt_noncurrent"] = debt_noncurrent
        facts["free_cash_flow"] = None
        accession_compact = accession.replace("-", "")
        primary_document = filing.get("primary_document") or ""
        source_url = (
            f"https://www.sec.gov/Archives/edgar/data/{cik_numeric}/{accession_compact}/{primary_document}"
            if primary_document
            else f"https://www.sec.gov/Archives/edgar/data/{cik_numeric}/{accession_compact}/"
        )
        revisions.append(build_statement_revision(
            ticker=ticker,
            cik=cik10,
            form_type=filing["form_type"],
            accession_number=accession,
            filing_date=filing.get("filing_date"),
            source_published_at=filing.get("source_published_at"),
            period_end_date=period_end,
            fiscal_year=fiscal_year,
            fiscal_quarter=fiscal_quarter,
            currency=currency,
            facts=facts,
            source_url=source_url,
        ))
    return revisions

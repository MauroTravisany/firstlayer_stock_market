import os
import re

import requests

from .point_in_time import build_statement_revision

SEC_DATA_BASE = "https://data.sec.gov"
SEC_FORMS = {"10-Q", "10-Q/A", "10-K", "10-K/A", "20-F", "20-F/A", "40-F", "40-F/A"}


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
    cik10 = normalize_cik(cik)
    return _get_json(f"{SEC_DATA_BASE}/submissions/CIK{cik10}.json")


def fetch_companyfacts(cik):
    cik10 = normalize_cik(cik)
    return _get_json(f"{SEC_DATA_BASE}/api/xbrl/companyfacts/CIK{cik10}.json")


def recent_filings_by_accession(submissions):
    recent = (submissions.get("filings") or {}).get("recent") or {}
    accessions = recent.get("accessionNumber") or []
    rows = {}
    for index, accession in enumerate(accessions):
        def value(name):
            values = recent.get(name) or []
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
    for taxonomy in ("us-gaap", "ifrs-full"):
        namespace = facts.get(taxonomy) or {}
        for concept in concepts:
            units = (namespace.get(concept) or {}).get("units") or {}
            for unit in unit_preferences:
                for row in units.get(unit) or []:
                    if row.get("accn") == accession and (not period_end or row.get("end") == period_end):
                        yield row, unit


def _choose_fact(companyfacts, concepts, *, accession, period_end, unit_preferences):
    matches = list(_matching_fact_rows(
        companyfacts, concepts, accession=accession, period_end=period_end,
        unit_preferences=unit_preferences,
    ))
    if not matches:
        return None, None, None
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
        "total_debt": (["LongTermDebtAndFinanceLeaseObligationsCurrent", "LongTermDebtCurrent", "LongTermDebtNoncurrent"], ["USD"]),
        "shareholders_equity": (["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"], ["USD"]),
        "operating_cash_flow": (["NetCashProvidedByUsedInOperatingActivities"], ["USD"]),
    }
    cik10 = normalize_cik(cik)
    cik_numeric = str(int(cik10))
    for accession, filing in filings.items():
        period_end = filing.get("period_end_date")
        if not period_end:
            continue
        fiscal_year, fiscal_quarter = _fiscal_metadata(companyfacts, accession, period_end)
        facts = {}
        currency = None
        for field, (concepts, units) in mappings.items():
            value, unit, _metadata = _choose_fact(
                companyfacts, concepts, accession=accession, period_end=period_end,
                unit_preferences=units,
            )
            facts[field] = value
            if field == "revenue" and unit == "USD":
                currency = "USD"
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
            fiscal_year=fiscal_year if fiscal_year is not None else int(period_end[:4]),
            fiscal_quarter=fiscal_quarter,
            currency=currency,
            facts=facts,
            source_url=source_url,
        ))
    return revisions

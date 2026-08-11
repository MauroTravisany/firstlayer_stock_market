import os
import re
from datetime import date

import requests

from .point_in_time import build_statement_revision


SEC_DATA_BASE = "https://data.sec.gov"
SEC_FORMS = {
    "10-Q",
    "10-Q/A",
    "10-K",
    "10-K/A",
    "20-F",
    "20-F/A",
    "40-F",
    "40-F/A",
}
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
        raise RuntimeError(
            "SEC_USER_AGENT must identify the application and include a contact email"
        )
    return {
        "User-Agent": user_agent,
        "Accept-Encoding": "gzip, deflate",
        "Accept": "application/json",
    }


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
    """Normalize current and historical SEC submission arrays by accession."""
    rows = {}
    for document in _filing_documents(submissions):
        accessions = document.get("accessionNumber") or []
        for index, accession in enumerate(accessions):

            def value(name):
                values = document.get(name) or []
                return values[index] if index < len(values) else None

            form = value("form")
            if not accession or form not in SEC_FORMS:
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


def _matching_fact_rows(
    companyfacts, concepts, *, accession, period_end, unit_preferences
):
    facts = companyfacts.get("facts") or {}
    for taxonomy in ("us-gaap", "ifrs-full", "dei"):
        namespace = facts.get(taxonomy) or {}
        for concept_priority, concept in enumerate(concepts):
            units = (namespace.get(concept) or {}).get("units") or {}
            for unit_priority, unit in enumerate(unit_preferences):
                for row in units.get(unit) or []:
                    if row.get("accn") == accession and (
                        not period_end or row.get("end") == period_end
                    ):
                        yield {
                            "row": row,
                            "unit": unit,
                            "taxonomy": taxonomy,
                            "concept": concept,
                            "concept_priority": concept_priority,
                            "unit_priority": unit_priority,
                        }


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


def _filed_rank(value):
    text = str(value or "").replace("-", "")
    return int(text) if text.isdigit() else 0


def _fact_rank(candidate, duration_target):
    row = candidate["row"]
    duration = _duration_days(row)
    duration_penalty = (
        abs(duration - duration_target)
        if duration_target is not None and duration is not None
        else (10_000 if duration_target is not None else 0)
    )
    return (
        duration_penalty,
        candidate["concept_priority"],
        candidate["unit_priority"],
        0 if row.get("frame") else 1,
        -_filed_rank(row.get("filed")),
        -int(row.get("fy") or 0),
        str(row.get("start") or ""),
    )


def _choose_fact(
    companyfacts,
    concepts,
    *,
    accession,
    period_end,
    unit_preferences,
    duration_target=None,
    require_duration=False,
):
    matches = list(
        _matching_fact_rows(
            companyfacts,
            concepts,
            accession=accession,
            period_end=period_end,
            unit_preferences=unit_preferences,
        )
    )
    if require_duration:
        matches = [
            candidate
            for candidate in matches
            if _duration_days(candidate["row"]) is not None
        ]
    if not matches:
        return None, None, None

    ranked = sorted(matches, key=lambda candidate: _fact_rank(candidate, duration_target))
    chosen = ranked[0]
    row = chosen["row"]
    if duration_target is not None:
        duration = _duration_days(row)
        tolerance = 35 if duration_target == 91 else 75
        if duration is None or abs(duration - duration_target) > tolerance:
            return None, None, None

    best_rank = _fact_rank(chosen, duration_target)
    tied = [candidate for candidate in ranked if _fact_rank(candidate, duration_target) == best_rank]
    distinct_values = {str(candidate["row"].get("val")) for candidate in tied}
    if len(distinct_values) > 1:
        return None, None, None
    return row.get("val"), chosen["unit"], row


def _fiscal_metadata(companyfacts, accession, period_end, currency):
    concepts = [
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
        "Revenue",
        "NetIncomeLoss",
        "ProfitLoss",
    ]
    candidates = []
    for candidate in _matching_fact_rows(
        companyfacts,
        concepts,
        accession=accession,
        period_end=period_end,
        unit_preferences=[currency],
    ):
        row = candidate["row"]
        if row.get("fy") is not None and row.get("fp"):
            candidates.append(candidate)
    if not candidates:
        return None, None
    candidates.sort(
        key=lambda candidate: (
            -_filed_rank(candidate["row"].get("filed")),
            candidate["concept_priority"],
            str(candidate["row"].get("start") or ""),
        )
    )
    chosen = candidates[0]["row"]
    fp = str(chosen.get("fp") or "").upper()
    quarter = {"Q1": 1, "Q2": 2, "Q3": 3, "FY": 4}.get(fp)
    return int(chosen["fy"]), quarter


def _debt_values(companyfacts, accession, period_end, currency):
    kwargs = dict(
        accession=accession,
        period_end=period_end,
        unit_preferences=[currency],
    )
    total, _, _ = _choose_fact(
        companyfacts,
        [
            "LongTermDebtAndFinanceLeaseObligations",
            "DebtAndFinanceLeaseObligations",
            "Borrowings",
        ],
        **kwargs,
    )
    current, _, _ = _choose_fact(
        companyfacts,
        [
            "LongTermDebtAndFinanceLeaseObligationsCurrent",
            "LongTermDebtCurrent",
            "DebtCurrent",
            "CurrentBorrowings",
        ],
        **kwargs,
    )
    noncurrent, _, _ = _choose_fact(
        companyfacts,
        [
            "LongTermDebtAndFinanceLeaseObligationsNoncurrent",
            "LongTermDebtNoncurrent",
            "NoncurrentBorrowings",
        ],
        **kwargs,
    )
    if total is None and (current is not None or noncurrent is not None):
        total = float(current or 0) + float(noncurrent or 0)
    return total, current, noncurrent


def build_sec_statement_revisions(
    ticker,
    cik,
    submissions,
    companyfacts,
    *,
    reporting_currency,
    mapping_version,
):
    currency = str(reporting_currency or "").upper()
    if len(currency) != 3 or not currency.isalpha():
        raise ValueError("reporting_currency must be an ISO-like three-letter code")

    filings = recent_filings_by_accession(submissions)
    revisions = []
    mappings = {
        "revenue": (
            [
                "RevenueFromContractWithCustomerExcludingAssessedTax",
                "Revenues",
                "SalesRevenueNet",
                "Revenue",
            ],
            [currency],
        ),
        "gross_profit": (["GrossProfit"], [currency]),
        "operating_income": (
            [
                "OperatingIncomeLoss",
                "ProfitLossFromOperatingActivities",
                "OperatingProfitLoss",
            ],
            [currency],
        ),
        "net_income": (["NetIncomeLoss", "ProfitLoss"], [currency]),
        "eps_basic": (
            ["EarningsPerShareBasic", "BasicEarningsLossPerShare"],
            [f"{currency}/shares", f"{currency} / shares"],
        ),
        "eps_diluted": (
            ["EarningsPerShareDiluted", "DilutedEarningsLossPerShare"],
            [f"{currency}/shares", f"{currency} / shares"],
        ),
        "total_assets": (["Assets"], [currency]),
        "total_liabilities": (["Liabilities"], [currency]),
        "shareholders_equity": (
            [
                "StockholdersEquity",
                "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                "Equity",
            ],
            [currency],
        ),
        "operating_cash_flow": (
            [
                "NetCashProvidedByUsedInOperatingActivities",
                "CashFlowsFromUsedInOperatingActivities",
            ],
            [currency],
        ),
        "cash_and_equivalents": (
            [
                "CashAndCashEquivalentsAtCarryingValue",
                "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
                "CashAndCashEquivalents",
            ],
            [currency],
        ),
        "shares_outstanding": (
            ["EntityCommonStockSharesOutstanding", "CommonStockSharesOutstanding"],
            ["shares"],
        ),
    }
    cik10 = normalize_cik(cik)
    cik_numeric = str(int(cik10))
    for accession, filing in filings.items():
        period_end = filing.get("period_end_date")
        if not period_end:
            continue
        fiscal_year, fiscal_quarter = _fiscal_metadata(
            companyfacts, accession, period_end, currency
        )
        duration_target = _target_duration(filing.get("form_type"), fiscal_quarter)
        facts = {}
        for field, (concepts, units) in mappings.items():
            is_duration = field in DURATION_FACTS
            value, _unit, _metadata = _choose_fact(
                companyfacts,
                concepts,
                accession=accession,
                period_end=period_end,
                unit_preferences=units,
                duration_target=duration_target if is_duration else None,
                require_duration=is_duration,
            )
            facts[field] = value
        total_debt, debt_current, debt_noncurrent = _debt_values(
            companyfacts, accession, period_end, currency
        )
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
        revisions.append(
            build_statement_revision(
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
                mapping_version=mapping_version,
            )
        )
    return sorted(
        revisions,
        key=lambda row: (
            row.get("period_end_date") or "",
            row.get("available_at") or "9999-12-31T23:59:59Z",
            row.get("source_record_id") or "",
            row.get("revision_id") or "",
        ),
    )

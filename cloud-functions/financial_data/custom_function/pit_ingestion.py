import os

from .data_processing import write_json_lines
from .financial_mapping import ticker_cik_map
from .sec_source import build_sec_statement_revisions, fetch_companyfacts, fetch_submissions


def save_pit_financial_statements_to_json(ticker, snapshot_date, config):
    mapping_version, mapping, _mapping_path = ticker_cik_map(config)
    mapping_entry = mapping.get(ticker.upper())
    if not mapping_entry:
        raise RuntimeError(
            f"No entry in mapping {mapping_version} for {ticker}; PIT ingestion fails closed"
        )
    if mapping_entry["financial_reporting"] == "NOT_APPLICABLE":
        return {
            "not_applicable": True,
            "statements_file": None,
            "statements_count": 0,
            "eligible_count": 0,
            "mapping_version": mapping_version,
            "data_status": "PIT_FINANCIAL_NOT_APPLICABLE",
            "severity": "OK",
            "message": (
                f"Fundamental statements are not applicable to {ticker} under "
                f"mapping {mapping_version}."
            ),
        }

    if not config.get("sec_user_agent"):
        raise RuntimeError("SEC_USER_AGENT is required when USE_PIT_FINANCIALS=true")
    os.environ["SEC_USER_AGENT"] = config["sec_user_agent"]
    cik = mapping_entry["cik"]
    submissions = fetch_submissions(cik)
    companyfacts = fetch_companyfacts(cik)
    revisions = build_sec_statement_revisions(
        ticker,
        cik,
        submissions,
        companyfacts,
        reporting_currency=mapping_entry["reporting_currency"],
        mapping_version=mapping_version,
    )
    eligible = [row for row in revisions if row.get("backtest_eligible")]
    filename = f"{ticker}_financial_statements_pit_{snapshot_date}.json"
    write_json_lines(filename, revisions)
    return {
        "not_applicable": False,
        "statements_file": filename,
        "statements_count": len(revisions),
        "eligible_count": len(eligible),
        "mapping_version": mapping_version,
        "data_status": (
            "PIT_FINANCIAL_OK" if eligible else "PIT_FINANCIAL_NO_ELIGIBLE_ROWS"
        ),
        "severity": "OK" if eligible else "ERROR",
        "message": (
            f"SEC EDGAR returned {len(revisions)} immutable revisions under "
            f"{mapping_version}; {len(eligible)} are backtest eligible."
        ),
    }

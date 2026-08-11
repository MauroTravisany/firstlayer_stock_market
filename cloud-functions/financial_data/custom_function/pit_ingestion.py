import json
import os

from .data_processing import write_json_lines
from .sec_source import build_sec_statement_revisions, fetch_companyfacts, fetch_submissions


def _ticker_cik_map(config):
    try:
        mapping = json.loads(config.get("ticker_cik_map_json") or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError("TICKER_CIK_MAP_JSON must be valid JSON") from exc
    return {str(k).upper(): str(v) for k, v in mapping.items()}


def save_pit_financial_statements_to_json(ticker, snapshot_date, config):
    if not config.get("sec_user_agent"):
        raise RuntimeError("SEC_USER_AGENT is required when USE_PIT_FINANCIALS=true")
    os.environ["SEC_USER_AGENT"] = config["sec_user_agent"]
    cik = _ticker_cik_map(config).get(ticker.upper())
    if not cik:
        raise RuntimeError(f"No versioned CIK mapping configured for {ticker}; PIT ingestion fails closed")

    submissions = fetch_submissions(cik)
    companyfacts = fetch_companyfacts(cik)
    revisions = build_sec_statement_revisions(ticker, cik, submissions, companyfacts)
    eligible = [row for row in revisions if row.get("backtest_eligible")]
    filename = f"{ticker}_financial_statements_pit_{snapshot_date}.json"
    write_json_lines(filename, revisions)
    return {
        "statements_file": filename,
        "statements_count": len(revisions),
        "eligible_count": len(eligible),
        "data_status": "PIT_FINANCIAL_OK" if eligible else "PIT_FINANCIAL_NO_ELIGIBLE_ROWS",
        "severity": "OK" if eligible else "ERROR",
        "message": f"SEC EDGAR returned {len(revisions)} immutable revisions; {len(eligible)} are backtest eligible.",
    }

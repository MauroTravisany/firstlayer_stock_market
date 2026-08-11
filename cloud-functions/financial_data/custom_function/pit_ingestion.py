import json
import os
from pathlib import Path

from .data_processing import write_json_lines
from .sec_source import build_sec_statement_revisions, fetch_companyfacts, fetch_submissions


DEFAULT_MAPPING_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "ticker_cik_map.v1.json"
)


def _load_mapping_document(config):
    inline = config.get("ticker_cik_map_json")
    if inline:
        try:
            document = json.loads(inline)
        except json.JSONDecodeError as exc:
            raise RuntimeError("TICKER_CIK_MAP_JSON must be valid JSON") from exc
    else:
        path = Path(config.get("ticker_cik_map_path") or DEFAULT_MAPPING_PATH)
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"Unable to read versioned ticker/CIK mapping: {path}") from exc

    if not isinstance(document, dict):
        raise RuntimeError("Ticker/CIK mapping root must be an object")
    mapping_version = str(document.get("mapping_version") or "").strip()
    expected_version = str(config.get("ticker_cik_map_version") or "").strip()
    if not mapping_version:
        raise RuntimeError("Ticker/CIK mapping must declare mapping_version")
    if expected_version and mapping_version != expected_version:
        raise RuntimeError(
            f"Ticker/CIK mapping version mismatch: expected {expected_version}, got {mapping_version}"
        )
    entries = document.get("entries")
    if not isinstance(entries, list) or not entries:
        raise RuntimeError("Ticker/CIK mapping must contain a non-empty entries list")
    return mapping_version, entries


def _ticker_cik_map(config):
    mapping_version, entries = _load_mapping_document(config)
    mapping = {}
    for index, raw in enumerate(entries):
        if not isinstance(raw, dict):
            raise RuntimeError(f"Ticker/CIK mapping entry {index} must be an object")
        ticker = str(raw.get("ticker") or "").strip().upper()
        cik = "".join(character for character in str(raw.get("cik") or "") if character.isdigit())
        currency = str(raw.get("reporting_currency") or "").strip().upper()
        if not ticker:
            raise RuntimeError(f"Ticker/CIK mapping entry {index} has no ticker")
        if ticker in mapping:
            raise RuntimeError(f"Ticker/CIK mapping contains duplicate ticker {ticker}")
        if not cik or len(cik) > 10:
            raise RuntimeError(f"Ticker/CIK mapping entry {ticker} has invalid CIK")
        if len(currency) != 3 or not currency.isalpha():
            raise RuntimeError(
                f"Ticker/CIK mapping entry {ticker} has invalid reporting_currency"
            )
        mapping[ticker] = {
            "cik": cik.zfill(10),
            "reporting_currency": currency,
            "issuer_name": str(raw.get("issuer_name") or "").strip() or None,
        }
    return mapping_version, mapping


def save_pit_financial_statements_to_json(ticker, snapshot_date, config):
    if not config.get("sec_user_agent"):
        raise RuntimeError("SEC_USER_AGENT is required when USE_PIT_FINANCIALS=true")
    os.environ["SEC_USER_AGENT"] = config["sec_user_agent"]
    mapping_version, mapping = _ticker_cik_map(config)
    mapping_entry = mapping.get(ticker.upper())
    if not mapping_entry:
        raise RuntimeError(
            f"No entry in mapping {mapping_version} for {ticker}; PIT ingestion fails closed"
        )

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
        "statements_file": filename,
        "statements_count": len(revisions),
        "eligible_count": len(eligible),
        "mapping_version": mapping_version,
        "data_status": "PIT_FINANCIAL_OK" if eligible else "PIT_FINANCIAL_NO_ELIGIBLE_ROWS",
        "severity": "OK" if eligible else "ERROR",
        "message": (
            f"SEC EDGAR returned {len(revisions)} immutable revisions under "
            f"{mapping_version}; {len(eligible)} are backtest eligible."
        ),
    }

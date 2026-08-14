import json
from pathlib import Path


DEFAULT_MAPPING_PATH = (
    Path(__file__).resolve().parents[1] / "config" / "ticker_cik_map.v1.json"
)
FINANCIAL_REPORTING_MODES = {"SEC_EDGAR", "NOT_APPLICABLE"}


def load_mapping_document(config):
    path = Path(config.get("ticker_cik_map_path") or DEFAULT_MAPPING_PATH)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"Unable to read versioned ticker/CIK mapping: {path}"
        ) from exc

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
    return mapping_version, entries, path


def ticker_cik_map(config):
    mapping_version, entries, path = load_mapping_document(config)
    mapping = {}
    for index, raw in enumerate(entries):
        if not isinstance(raw, dict):
            raise RuntimeError(f"Ticker/CIK mapping entry {index} must be an object")
        ticker = str(raw.get("ticker") or "").strip().upper()
        mode = str(raw.get("financial_reporting") or "SEC_EDGAR").strip().upper()
        if not ticker:
            raise RuntimeError(f"Ticker/CIK mapping entry {index} has no ticker")
        if ticker in mapping:
            raise RuntimeError(f"Ticker/CIK mapping contains duplicate ticker {ticker}")
        if mode not in FINANCIAL_REPORTING_MODES:
            raise RuntimeError(
                f"Ticker/CIK mapping entry {ticker} has invalid financial_reporting"
            )

        entry = {
            "financial_reporting": mode,
            "issuer_name": str(raw.get("issuer_name") or "").strip() or None,
        }
        if mode == "SEC_EDGAR":
            cik = "".join(
                character
                for character in str(raw.get("cik") or "")
                if character.isdigit()
            )
            currency = str(raw.get("reporting_currency") or "").strip().upper()
            if not cik or len(cik) > 10:
                raise RuntimeError(
                    f"Ticker/CIK mapping entry {ticker} has invalid CIK"
                )
            if len(currency) != 3 or not currency.isalpha():
                raise RuntimeError(
                    f"Ticker/CIK mapping entry {ticker} has invalid reporting_currency"
                )
            entry.update(
                {
                    "cik": cik.zfill(10),
                    "reporting_currency": currency,
                }
            )
        mapping[ticker] = entry
    return mapping_version, mapping, path

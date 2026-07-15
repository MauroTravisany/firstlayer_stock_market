import json
import logging
import os
import sys
from datetime import date, datetime

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from conf.conf import load_config

logging.basicConfig(level=logging.INFO)


def parse_tickers(value):
    if isinstance(value, str):
        value = value.replace(";", ",").split(",")

    return [str(ticker).strip().upper() for ticker in value if str(ticker).strip()]


def parse_snapshot_date(value):
    if not value:
        return date.today()
    return datetime.strptime(value, "%Y-%m-%d").date()


def default_tickers():
    return parse_tickers(os.environ.get("TICKERS", "AAPL"))


def process_ticker(ticker, config, snapshot_date):
    from custom_function.bq_operations import merge_financial_ratios, merge_financial_statements
    from custom_function.data_processing import save_financial_data_to_json
    from custom_function.gcs_operations import upload_to_gcs

    files = save_financial_data_to_json(ticker, snapshot_date)
    bucket_name = config["bucket_name"]

    statements_blob = f"{ticker}/financial_statements/{files['statements_file']}" if files["statements_file"] else None
    ratios_blob = f"{ticker}/financial_ratios/{files['ratios_file']}"

    upload_to_gcs(bucket_name, files["ratios_file"], ratios_blob)

    if files["statements_count"] > 0 and statements_blob:
        upload_to_gcs(bucket_name, files["statements_file"], statements_blob)
        merge_financial_statements(
            config["financial_statements_table"],
            f"gs://{bucket_name}/{statements_blob}",
        )

    merge_financial_ratios(
        config["financial_ratios_table"],
        f"gs://{bucket_name}/{ratios_blob}",
    )

    return {
        "status": "success",
        "ticker": ticker,
        "snapshot_date": str(snapshot_date),
        "financial_statements_rows": files["statements_count"],
        "financial_ratios_rows": files["ratios_count"],
    }


def main(request):
    request_json = request.get_json(silent=True) or {}

    try:
        tickers = parse_tickers(request_json.get("tickers", default_tickers()))
        snapshot_date = parse_snapshot_date(request_json.get("snapshot_date") or os.environ.get("SNAPSHOT_DATE"))
    except ValueError as exc:
        return json.dumps({"status": "error", "message": str(exc)}), 400, {"Content-Type": "application/json"}

    if not tickers:
        return json.dumps({"status": "error", "message": "No tickers provided"}), 400, {"Content-Type": "application/json"}

    try:
        config = load_config()
    except Exception as exc:
        logging.exception("Error al cargar configuracion")
        return json.dumps({"status": "error", "message": str(exc)}), 500, {"Content-Type": "application/json"}

    results = []
    for ticker in tickers:
        try:
            logging.info("Iniciando ETL financiero para %s", ticker)
            results.append(process_ticker(ticker, config, snapshot_date))
        except Exception as exc:
            logging.exception("Fallo ETL financiero para %s", ticker)
            results.append({"status": "error", "ticker": ticker, "message": str(exc)})

    status_code = 207 if any(result["status"] == "error" for result in results) else 200
    return json.dumps(results), status_code, {"Content-Type": "application/json"}


if __name__ == "__main__":
    from functions_framework import create_app

    port = int(os.environ.get("PORT", 8080))
    app = create_app("main")
    app.run(host="0.0.0.0", port=port)

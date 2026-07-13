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


def parse_target_date(value):
    if not value:
        return date.today()

    return datetime.strptime(value, "%Y-%m-%d").date()


def default_tickers():
    return parse_tickers(os.environ.get("TICKERS", "AAPL"))


def process_ticker(ticker, bucket_name, bq_table, target_date):
    from custom_function.bq_operations import load_data_to_bigquery
    from custom_function.data_processing import save_data_to_json
    from custom_function.gcs_operations import upload_to_gcs

    output_file = f"{ticker}_{target_date}.json"
    gcs_output_path = f"gs://{bucket_name}/{ticker}/{output_file}"

    save_data_to_json(ticker, output_file, target_date)
    upload_to_gcs(bucket_name, output_file, f"{ticker}/{output_file}")
    load_data_to_bigquery(bq_table, gcs_output_path)

    logging.info("Proceso completado exitosamente para %s en la fecha %s", ticker, target_date)
    return {"status": "success", "ticker": ticker, "message": "Proceso completado con exito"}


def main(request):
    request_json = request.get_json(silent=True) or {}

    try:
        tickers_input = parse_tickers(request_json.get("tickers", default_tickers()))
        target_date = parse_target_date(request_json.get("target_date") or os.environ.get("TARGET_DATE"))
    except ValueError as exc:
        return json.dumps({"status": "error", "message": str(exc)}), 400, {"Content-Type": "application/json"}

    if not tickers_input:
        return json.dumps({"status": "error", "message": "No tickers provided"}), 400, {"Content-Type": "application/json"}

    try:
        bucket_name, bq_table = load_config()
    except Exception as exc:
        logging.exception("Error al cargar configuracion desde Secret Manager")
        return json.dumps({"status": "error", "message": str(exc)}), 500, {"Content-Type": "application/json"}

    results = []

    for ticker in tickers_input:
        try:
            logging.info("Iniciando proceso para el ticker %s en la fecha %s", ticker, target_date)
            results.append(process_ticker(ticker, bucket_name, bq_table, target_date))
        except Exception as exc:
            logging.exception("El proceso fallo para el ticker %s en la fecha %s", ticker, target_date)
            results.append({"status": "error", "ticker": ticker, "message": str(exc)})

    status_code = 207 if any(item["status"] == "error" for item in results) else 200
    return json.dumps(results), status_code, {"Content-Type": "application/json"}


if __name__ == "__main__":
    from functions_framework import create_app

    port = int(os.environ.get("PORT", 8080))
    app = create_app("main")
    app.run(host="0.0.0.0", port=port)

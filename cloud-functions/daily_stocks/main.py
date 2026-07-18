import json
import logging
import os
import sys
from datetime import date, datetime

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from conf.conf import load_config

logging.basicConfig(level=logging.INFO)


def parse_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "y", "si"}


def parse_tickers(value):
    if isinstance(value, str):
        value = value.replace(";", ",").split(",")

    return [str(ticker).strip().upper() for ticker in value if str(ticker).strip()]


def parse_target_date(value):
    if not value:
        return date.today()

    return datetime.strptime(value, "%Y-%m-%d").date()


def default_tickers():
    return parse_tickers(os.environ.get("TICKERS", ""))


def resolve_tickers(request_json, config):
    if "tickers" in request_json:
        return parse_tickers(request_json.get("tickers"))

    from custom_function.portfolio_operations import fetch_enabled_tickers

    tickers = fetch_enabled_tickers(config["project_id"], config["portfolio_table"])
    if tickers:
        return tickers

    return default_tickers()


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
    dry_run = parse_bool(request_json.get("dry_run", request.args.get("dry_run")), False)

    try:
        target_date = parse_target_date(request_json.get("target_date") or os.environ.get("TARGET_DATE"))
    except ValueError as exc:
        return json.dumps({"status": "error", "message": str(exc)}), 400, {"Content-Type": "application/json"}

    try:
        config = load_config()
        tickers_input = resolve_tickers(request_json, config)
    except Exception as exc:
        logging.exception("Error al cargar configuracion o portafolio")
        return json.dumps({"status": "error", "message": str(exc)}), 500, {"Content-Type": "application/json"}

    if not tickers_input:
        return json.dumps({"status": "error", "message": "No enabled tickers found in portfolio"}), 400, {"Content-Type": "application/json"}

    if dry_run:
        return (
            json.dumps(
                {
                    "status": "dry_run",
                    "target_date": str(target_date),
                    "source": "portfolio_assets" if "tickers" not in request_json else "request",
                    "tickers": tickers_input,
                    "rows": len(tickers_input),
                }
            ),
            200,
            {"Content-Type": "application/json"},
        )

    results = []

    for ticker in tickers_input:
        try:
            logging.info("Iniciando proceso para el ticker %s en la fecha %s", ticker, target_date)
            results.append(process_ticker(ticker, config["bucket_name"], config["bq_table"], target_date))
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

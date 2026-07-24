import json
import logging
import os
import sys
from datetime import date, datetime
from zoneinfo import ZoneInfo

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
        return datetime.now(ZoneInfo(os.environ.get("TIME_ZONE", "America/Santiago"))).date()

    return datetime.strptime(value, "%Y-%m-%d").date()


def parse_optional_date(value):
    if not value:
        return None

    return datetime.strptime(value, "%Y-%m-%d").date()


def default_tickers():
    return parse_tickers(os.environ.get("TICKERS", ""))


def infer_asset_type(ticker, asset_types):
    if ticker in asset_types:
        return asset_types[ticker]
    if ticker.endswith("-USD"):
        return "CRYPTO"
    return "STOCK"


def resolve_assets(request_json, config):
    if "tickers" in request_json:
        tickers = parse_tickers(request_json.get("tickers"))
        from custom_function.portfolio_operations import fetch_asset_types

        asset_types = fetch_asset_types(config["project_id"], config["portfolio_table"], tickers)
        return [{"ticker": ticker, "asset_type": infer_asset_type(ticker, asset_types)} for ticker in tickers]

    from custom_function.portfolio_operations import fetch_enabled_assets

    assets = fetch_enabled_assets(config["project_id"], config["portfolio_table"])
    if assets:
        return assets

    return [{"ticker": ticker, "asset_type": infer_asset_type(ticker, {})} for ticker in default_tickers()]


def process_ticker(ticker, bucket_name, bq_table, target_date, asset_type="STOCK", end_date=None):
    from custom_function.bq_operations import load_data_to_bigquery
    from custom_function.data_processing import save_data_to_json
    from custom_function.gcs_operations import upload_to_gcs

    output_suffix = f"{target_date}_{end_date}" if end_date and end_date != target_date + date.resolution else str(target_date)
    output_file = f"{ticker}_{output_suffix}.json"
    gcs_output_path = f"gs://{bucket_name}/{ticker}/{output_file}"

    rows_loaded = save_data_to_json(ticker, output_file, target_date, asset_type=asset_type, end_date=end_date)
    upload_to_gcs(bucket_name, output_file, f"{ticker}/{output_file}")
    load_data_to_bigquery(bq_table, gcs_output_path)

    logging.info("Proceso completado exitosamente para %s en la fecha %s", ticker, target_date)
    return {
        "status": "success",
        "ticker": ticker,
        "asset_type": asset_type,
        "message": "Proceso completado con exito",
        "data_status": "PRICE_OK",
        "severity": "OK",
        "rows_loaded": rows_loaded,
    }


def main(request):
    request_json = request.get_json(silent=True) or {}
    dry_run = parse_bool(request_json.get("dry_run", request.args.get("dry_run")), False)
    send_alert = parse_bool(request_json.get("send_alert", request.args.get("send_alert")), True)

    try:
        start_date = parse_optional_date(request_json.get("start_date") or request.args.get("start_date"))
        end_date = parse_optional_date(request_json.get("end_date") or request.args.get("end_date"))
        target_date = start_date or parse_target_date(
            request_json.get("target_date") or request.args.get("target_date") or os.environ.get("TARGET_DATE")
        )
        if end_date and end_date <= target_date:
            return (
                json.dumps({"status": "error", "message": "end_date must be greater than target_date/start_date"}),
                400,
                {"Content-Type": "application/json"},
            )
    except ValueError as exc:
        return json.dumps({"status": "error", "message": str(exc)}), 400, {"Content-Type": "application/json"}

    try:
        config = load_config()
        if request.args.get("tickers") and "tickers" not in request_json:
            from custom_function.portfolio_operations import fetch_asset_types

            tickers = parse_tickers(request.args.get("tickers"))
            asset_types = fetch_asset_types(config["project_id"], config["portfolio_table"], tickers)
            assets_input = [{"ticker": ticker, "asset_type": infer_asset_type(ticker, asset_types)} for ticker in tickers]
        else:
            assets_input = resolve_assets(request_json, config)
    except Exception as exc:
        logging.exception("Error al cargar configuracion o portafolio")
        return json.dumps({"status": "error", "message": str(exc)}), 500, {"Content-Type": "application/json"}

    if not assets_input:
        return json.dumps({"status": "error", "message": "No enabled tickers found in portfolio"}), 400, {"Content-Type": "application/json"}

    if dry_run:
        return (
            json.dumps(
                {
                    "status": "dry_run",
                    "target_date": str(target_date),
                    "end_date": str(end_date) if end_date else None,
                    "source": "portfolio_assets" if "tickers" not in request_json else "request",
                    "assets": assets_input,
                    "rows": len(assets_input),
                }
            ),
            200,
            {"Content-Type": "application/json"},
        )

    results = []

    for asset in assets_input:
        ticker = asset["ticker"]
        asset_type = asset.get("asset_type", "STOCK")
        try:
            logging.info("Iniciando proceso para el ticker %s en la fecha %s", ticker, target_date)
            results.append(
                process_ticker(
                    ticker,
                    config["bucket_name"],
                    config["bq_table"],
                    target_date,
                    asset_type=asset_type,
                    end_date=end_date,
                )
            )
        except Exception as exc:
            logging.exception("El proceso fallo para el ticker %s en la fecha %s", ticker, target_date)
            results.append(
                {
                    "status": "error",
                    "ticker": ticker,
                    "asset_type": asset_type,
                    "message": str(exc),
                    "data_status": "PRICE_MISSING",
                    "severity": "ERROR",
                    "rows_loaded": 0,
                }
            )

    alert_sent = False
    alert_error = None
    quality = None
    try:
        from custom_function.monitoring import persist_quality_events, quality_summary, send_quality_alert

        persist_quality_events(config, "stockdaily", target_date, results)
        quality = quality_summary(results)
        if send_alert:
            alert_sent, alert_error = send_quality_alert(config, "stockdaily", target_date, results)
    except Exception as exc:
        logging.exception("Fallo monitoreo de calidad stockdaily")
        alert_error = str(exc)

    status_code = 207 if any(item["status"] == "error" for item in results) else 200
    return (
        json.dumps({"results": results, "quality": quality, "alert_sent": alert_sent, "alert_error": alert_error}),
        status_code,
        {"Content-Type": "application/json"},
    )


if __name__ == "__main__":
    from functions_framework import create_app

    port = int(os.environ.get("PORT", 8080))
    app = create_app("main")
    app.run(host="0.0.0.0", port=port)

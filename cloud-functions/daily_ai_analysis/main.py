import json
import logging
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from conf.conf import load_config
from custom_function.ai_analysis import (
    analyze_ticker,
    build_analysis_row,
    build_error_analysis_row,
    build_portfolio_summary,
)
from custom_function.bq_operations import (
    ensure_tables,
    fetch_daily_signals,
    get_analysis_date,
    merge_analysis,
    merge_summary,
)
from custom_function.notifier import build_alert_text, send_webhook_alert

logging.basicConfig(level=logging.INFO)


def parse_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    return normalized in {"1", "true", "yes", "y", "si"}


def parse_tickers(value):
    if not value:
        return None
    if isinstance(value, str):
        value = value.replace(";", ",").split(",")
    return [str(ticker).strip().upper() for ticker in value if str(ticker).strip()]


def main(request):
    request_json = request.get_json(silent=True) or {}
    dry_run = parse_bool(request_json.get("dry_run", request.args.get("dry_run")), False)
    send_alert = parse_bool(request_json.get("send_alert", request.args.get("send_alert")), True)

    try:
        config = load_config()
        ensure_tables(config)
        analysis_date = get_analysis_date(config, request_json.get("analysis_date") or request.args.get("analysis_date"))
        tickers = parse_tickers(request_json.get("tickers") or request.args.get("tickers") or os.environ.get("TICKERS"))
        signals = fetch_daily_signals(config, analysis_date, tickers)
    except Exception as exc:
        logging.exception("Error preparando daily_ai_analysis")
        return json.dumps({"status": "error", "message": str(exc)}), 500, {"Content-Type": "application/json"}

    if not signals:
        return (
            json.dumps({"status": "error", "message": f"No signals found for {analysis_date}"}),
            404,
            {"Content-Type": "application/json"},
        )

    if dry_run:
        return (
            json.dumps(
                {
                    "status": "dry_run",
                    "analysis_date": str(analysis_date),
                    "tickers": [row["ticker"] for row in signals],
                    "rows": len(signals),
                }
            ),
            200,
            {"Content-Type": "application/json"},
        )

    results = []
    analysis_rows = []
    for signal_row in signals:
        ticker = signal_row["ticker"]
        try:
            logging.info("Generando analisis IA para %s", ticker)
            parsed, input_hash = analyze_ticker(config, signal_row)
            analysis_row = build_analysis_row(config, signal_row, parsed, input_hash)
            merge_analysis(config, analysis_row)
            analysis_rows.append(analysis_row)
            results.append({"ticker": ticker, "status": "success"})
        except Exception as exc:
            logging.exception("Fallo analisis IA para %s", ticker)
            error_row = build_error_analysis_row(config, signal_row, exc)
            try:
                merge_analysis(config, error_row)
            except Exception:
                logging.exception("Fallo guardando error de analisis para %s", ticker)
            analysis_rows.append(error_row)
            results.append({"ticker": ticker, "status": "error", "message": str(exc)})

    alert_sent = False
    alert_error = None
    alert_title = None
    try:
        portfolio_summary = build_portfolio_summary(config, analysis_rows)
        alert_title = portfolio_summary["alert_title"]
        alert_body = build_alert_text(portfolio_summary)

        if send_alert:
            alert_sent, alert_error = send_webhook_alert(config, portfolio_summary)

        merge_summary(
            config,
            {
                "analysis_date": analysis_date,
                "portfolio_summary": portfolio_summary["portfolio_summary"],
                "top_opportunities": portfolio_summary["top_opportunities"],
                "overvalued_summary": portfolio_summary["overvalued_summary"],
                "risk_summary": portfolio_summary["risk_summary"],
                "dashboard_summary": portfolio_summary["dashboard_summary"],
                "alert_title": alert_title,
                "alert_body": alert_body,
                "alert_sent": alert_sent,
                "alert_error": alert_error,
                "model_name": config["openai_model"],
                "prompt_version": config["prompt_version"],
            },
        )
    except Exception as exc:
        logging.exception("Fallo resumen o alerta diaria")
        alert_error = str(exc)

    status_code = 207 if any(item["status"] == "error" for item in results) or alert_error else 200
    return (
        json.dumps(
            {
                "status": "success" if status_code == 200 else "partial",
                "analysis_date": str(analysis_date),
                "processed": len(results),
                "results": results,
                "alert_sent": alert_sent,
                "alert_error": alert_error,
                "alert_title": alert_title,
            }
        ),
        status_code,
        {"Content-Type": "application/json"},
    )


if __name__ == "__main__":
    from functions_framework import create_app

    port = int(os.environ.get("PORT", 8080))
    app = create_app("main")
    app.run(host="0.0.0.0", port=port)

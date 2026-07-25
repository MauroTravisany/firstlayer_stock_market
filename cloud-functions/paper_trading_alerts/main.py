import json
import logging
import os
import sys
from datetime import datetime
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


def parse_date(value):
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def main(request):
    request_json = request.get_json(silent=True) or {}
    dry_run = parse_bool(request_json.get("dry_run", request.args.get("dry_run")), False)
    force = parse_bool(request_json.get("force", request.args.get("force")), False)
    alert_type = request_json.get("alert_type") or request.args.get("alert_type") or "paper_trading_daily"
    summary_date = parse_date(request_json.get("summary_date") or request.args.get("summary_date"))

    try:
        config = load_config()
        from custom_function.bq_operations import (
            already_sent,
            ensure_alerts_table,
            fetch_closed_trades,
            fetch_new_trades,
            fetch_summary,
            mark_sent,
        )
        from custom_function.notifier import send_alert

        ensure_alerts_table(config)
        summary = fetch_summary(config, summary_date)
        if not summary:
            return json.dumps({"status": "error", "message": "No trading summary found"}), 404, {"Content-Type": "application/json"}

        summary_date = summary["summary_date"]
        new_trades = fetch_new_trades(config, summary_date)
        closed_trades = fetch_closed_trades(config, summary_date)

        if dry_run:
            return (
                json.dumps(
                    {
                        "status": "dry_run",
                        "summary": {key: str(value) for key, value in summary.items()},
                        "new_trades": new_trades,
                        "closed_trades": closed_trades,
                    },
                    default=str,
                ),
                200,
                {"Content-Type": "application/json"},
            )

        if already_sent(config, summary_date, alert_type) and not force:
            return (
                json.dumps({"status": "skipped", "message": "Alert already sent", "summary_date": str(summary_date)}),
                200,
                {"Content-Type": "application/json"},
            )

        sent, error = send_alert(config, summary, new_trades, closed_trades)
        mark_sent(config, summary_date, alert_type, "SENT" if sent else "ERROR", error or "OK")
        status_code = 200 if sent else 500
        return (
            json.dumps({"status": "sent" if sent else "error", "summary_date": str(summary_date), "error": error}),
            status_code,
            {"Content-Type": "application/json"},
        )
    except Exception as exc:
        logging.exception("Paper trading alert failed")
        return json.dumps({"status": "error", "message": str(exc)}), 500, {"Content-Type": "application/json"}


if __name__ == "__main__":
    from functions_framework import create_app

    port = int(os.environ.get("PORT", 8080))
    app = create_app("main")
    app.run(host="0.0.0.0", port=port)

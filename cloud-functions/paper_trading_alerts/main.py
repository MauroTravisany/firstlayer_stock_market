import json
import logging
import os
import sys
from datetime import datetime, timedelta
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
    send_alert_enabled = parse_bool(request_json.get("send_alert", request.args.get("send_alert")), True)
    run_ai_feedback = parse_bool(request_json.get("run_ai_feedback", request.args.get("run_ai_feedback")), True)
    review_type = request_json.get("review_type") or request.args.get("review_type") or "daily_alert"
    lookback_weeks = int(request_json.get("lookback_weeks") or request.args.get("lookback_weeks") or 4)
    alert_frequency = request_json.get("alert_frequency") or request.args.get("alert_frequency") or "daily"
    alert_type = request_json.get("alert_type") or request.args.get("alert_type") or "paper_trading_daily"
    summary_date = parse_date(request_json.get("summary_date") or request.args.get("summary_date"))

    try:
        config = load_config()
        from custom_function.bq_operations import (
            already_sent,
            ensure_alerts_table,
            ensure_feedback_table,
            ensure_weekly_review_table,
            fetch_closed_trades,
            fetch_asset_profiles,
            fetch_new_trades,
            fetch_strategy_performance,
            fetch_cycle_profile_performance,
            fetch_multiweek_strategy_results,
            fetch_summary,
            fetch_weekly_global_summary,
            fetch_weekly_feedback,
            fetch_weekly_strategy_performance,
            fetch_weekly_ticker_performance,
            mark_sent,
            save_feedback,
            save_weekly_strategy_review,
        )
        from custom_function.ai_feedback import generate_trading_feedback, generate_weekly_strategy_review
        from custom_function.notifier import send_alert, send_weekly_alert

        ensure_alerts_table(config)
        ensure_feedback_table(config)
        ensure_weekly_review_table(config)

        if review_type == "weekly_strategy":
            if not summary_date:
                now = datetime.now(ZoneInfo(os.environ.get("TIME_ZONE", "America/Santiago"))).date()
                summary_date = now
            week_start = summary_date - timedelta(days=summary_date.weekday())
            week_end = week_start + timedelta(days=6)
            daily_feedback = fetch_weekly_feedback(config, week_end, lookback_days=7)
            multiweek_results = fetch_multiweek_strategy_results(config, week_end, lookback_weeks=lookback_weeks)
            asset_profiles = fetch_asset_profiles(config)
            cycle_profile_performance = fetch_cycle_profile_performance(config, week_end, lookback_weeks=lookback_weeks)
            review = generate_weekly_strategy_review(
                config,
                week_start,
                week_end,
                daily_feedback,
                multiweek_results,
                asset_profiles,
                cycle_profile_performance,
            )

            if not dry_run:
                save_weekly_strategy_review(
                    config,
                    week_start,
                    week_end,
                    review,
                    daily_feedback_count=len(daily_feedback),
                    lookback_weeks=lookback_weeks,
                )

            return (
                json.dumps(
                    {
                        "status": "dry_run" if dry_run else "weekly_strategy_review_saved",
                        "week_start": str(week_start),
                        "week_end": str(week_end),
                        "daily_feedback_count": len(daily_feedback),
                        "multiweek_result_rows": len(multiweek_results),
                        "review": review,
                    },
                    default=str,
                ),
                200,
                {"Content-Type": "application/json"},
            )

        if review_type == "weekly_global_summary":
            if not summary_date:
                now = datetime.now(ZoneInfo(os.environ.get("TIME_ZONE", "America/Santiago"))).date()
                summary_date = now
            week_start = summary_date - timedelta(days=summary_date.weekday())
            week_end = week_start + timedelta(days=6)
            weekly_summary = fetch_weekly_global_summary(config, week_end)
            if not weekly_summary:
                return json.dumps({"status": "error", "message": "No weekly trading summary found"}), 404, {"Content-Type": "application/json"}
            strategy_week = fetch_weekly_strategy_performance(config, week_end)
            ticker_week = fetch_weekly_ticker_performance(config, week_end)
            weekly_alert_type = "paper_trading_weekly_global"

            if dry_run:
                return (
                    json.dumps(
                        {
                            "status": "dry_run",
                            "week_start": str(week_start),
                            "week_end": str(week_end),
                            "weekly_summary": weekly_summary,
                            "strategy_performance": strategy_week,
                            "ticker_performance": ticker_week,
                        },
                        default=str,
                    ),
                    200,
                    {"Content-Type": "application/json"},
                )

            if not send_alert_enabled:
                return (
                    json.dumps({"status": "processed_no_alert", "week_start": str(week_start), "week_end": str(week_end)}),
                    200,
                    {"Content-Type": "application/json"},
                )

            if already_sent(config, week_end, weekly_alert_type) and not force:
                return (
                    json.dumps({"status": "skipped", "message": "Weekly alert already sent", "week_end": str(week_end)}),
                    200,
                    {"Content-Type": "application/json"},
                )

            sent, error = send_weekly_alert(config, weekly_summary, strategy_week, ticker_week)
            mark_sent(config, week_end, weekly_alert_type, "SENT" if sent else "ERROR", error or "OK")
            return (
                json.dumps({"status": "sent" if sent else "error", "week_end": str(week_end), "error": error}),
                200 if sent else 500,
                {"Content-Type": "application/json"},
            )

        summary = fetch_summary(config, summary_date)
        if not summary:
            return json.dumps({"status": "error", "message": "No trading summary found"}), 404, {"Content-Type": "application/json"}

        summary_date = summary["summary_date"]
        if alert_frequency == "intraday" and alert_type == "paper_trading_daily":
            now = datetime.now(ZoneInfo(os.environ.get("TIME_ZONE", "America/Santiago")))
            slot_hour = (now.hour // 4) * 4
            alert_type = f"paper_trading_intraday_{slot_hour:02d}00"
        new_trades = fetch_new_trades(config, summary_date)
        closed_trades = fetch_closed_trades(config, summary_date)
        strategy_performance = fetch_strategy_performance(config)
        asset_profiles = fetch_asset_profiles(config)
        feedback = None

        if run_ai_feedback and config.get("ai_feedback_enabled"):
            try:
                feedback = generate_trading_feedback(config, summary, new_trades, closed_trades, strategy_performance, asset_profiles)
            except Exception as exc:
                logging.exception("AI trading feedback failed")
                feedback = {
                    "executive_summary": f"Feedback IA no disponible por error: {exc}",
                    "what_worked": "",
                    "what_failed": "",
                    "risk_notes": "La alerta continua sin bloquearse aunque falle la IA.",
                    "parameter_suggestions": "",
                    "news_needed": "",
                    "next_actions": "Revisar logs del servicio papertradingalerts.",
                    "confidence_score": 0,
                    "raw_response": str(exc),
                }
            if not dry_run:
                save_feedback(config, summary_date, feedback)

        if dry_run:
            return (
                json.dumps(
                    {
                        "status": "dry_run",
                        "summary": {key: str(value) for key, value in summary.items()},
                        "new_trades": new_trades,
                        "closed_trades": closed_trades,
                        "strategy_performance": strategy_performance,
                        "feedback": feedback,
                    },
                    default=str,
                ),
                200,
                {"Content-Type": "application/json"},
            )

        if not send_alert_enabled:
            return (
                json.dumps({"status": "processed_no_alert", "summary_date": str(summary_date), "feedback_saved": feedback is not None}),
                200,
                {"Content-Type": "application/json"},
            )

        if already_sent(config, summary_date, alert_type) and not force:
            return (
                json.dumps({"status": "skipped", "message": "Alert already sent", "summary_date": str(summary_date)}),
                200,
                {"Content-Type": "application/json"},
            )

        sent, error = send_alert(config, summary, new_trades, closed_trades, feedback)
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

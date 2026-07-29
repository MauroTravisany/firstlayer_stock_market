import json
import logging
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from conf.conf import load_config

logging.basicConfig(level=logging.INFO)


def main(request):
    try:
        config = load_config()
        request_json = request.get_json(silent=True) or {}

        from custom_function.bq_operations import (
            ensure_tables,
            fetch_portfolio_tickers,
            merge_earnings_rows,
            merge_market_rows,
            merge_news_rows,
        )
        from custom_function.data_sources import current_slot, fetch_earnings_rows, fetch_market_rows, fetch_news_rows
        from custom_function.data_sources import fetch_market_history_rows

        ensure_tables(config)
        mode = request_json.get("mode", "current")
        if mode in ("backfill_market_history", "market_history"):
            history_rows = fetch_market_history_rows(
                start_date=request_json.get("start_date"),
                end_date=request_json.get("end_date"),
                years=int(request_json.get("years", 5)),
                time_zone=config["time_zone"],
            )
            history_count = merge_market_rows(config, history_rows)
            return (
                json.dumps(
                    {
                        "status": "ok",
                        "mode": mode,
                        "market_rows": history_count,
                    }
                ),
                200,
                {"Content-Type": "application/json"},
            )

        tickers = request_json.get("tickers") or fetch_portfolio_tickers(config) or config["tickers"]
        slot = current_slot(config["time_zone"])
        market_rows = fetch_market_rows(slot)
        news_rows = fetch_news_rows(slot, config["gdelt_timespan"], config["gdelt_maxrecords"])
        earnings_rows = fetch_earnings_rows(slot, tickers)
        market_count = merge_market_rows(config, market_rows)
        news_count = merge_news_rows(config, news_rows)
        earnings_count = merge_earnings_rows(config, earnings_rows)

        return (
            json.dumps(
                {
                    "status": "ok",
                    "snapshot_slot": slot.isoformat(),
                    "market_rows": market_count,
                    "news_rows": news_count,
                    "earnings_rows": earnings_count,
                }
            ),
            200,
            {"Content-Type": "application/json"},
        )
    except Exception as exc:
        logging.exception("Macro data pipeline failed")
        return json.dumps({"status": "error", "message": str(exc)}), 500, {"Content-Type": "application/json"}


if __name__ == "__main__":
    from functions_framework import create_app

    port = int(os.environ.get("PORT", 8080))
    app = create_app("main")
    app.run(host="0.0.0.0", port=port)

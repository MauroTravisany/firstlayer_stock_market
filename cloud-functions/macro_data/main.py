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
        from custom_function.bq_operations import ensure_tables, merge_market_rows, merge_news_rows
        from custom_function.data_sources import current_slot, fetch_market_rows, fetch_news_rows

        ensure_tables(config)
        slot = current_slot(config["time_zone"])
        market_rows = fetch_market_rows(slot)
        news_rows = fetch_news_rows(slot, config["gdelt_timespan"], config["gdelt_maxrecords"])
        market_count = merge_market_rows(config, market_rows)
        news_count = merge_news_rows(config, news_rows)

        return (
            json.dumps(
                {
                    "status": "ok",
                    "snapshot_slot": slot.isoformat(),
                    "market_rows": market_count,
                    "news_rows": news_count,
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

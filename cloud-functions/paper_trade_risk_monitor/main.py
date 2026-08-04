import json
import logging
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
logging.basicConfig(level=logging.INFO)


def parse_bool(value, default=False):
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "y", "si"}


def request_values(request):
    values = request.get_json(silent=True) or {}
    if values:
        return values

    # Cloud Scheduler can send application/octet-stream. Accept its tiny,
    # constrained key:value body without weakening the public request contract.
    raw_body = request.get_data(cache=True, as_text=True).strip().strip("{}")
    for item in raw_body.split(","):
        key, separator, value = item.partition(":")
        if not separator:
            continue
        key = key.strip().strip('"')
        value = value.strip().strip('"')
        if key == "execute":
            values[key] = value.lower() == "true"
        elif key == "asset_scope" and value.lower() in {"all", "equities", "crypto"}:
            values[key] = value.lower()
    return values


def main(request):
    request_json = request_values(request)
    dry_run = parse_bool(request_json.get("dry_run", request.args.get("dry_run")), True)
    if request_json.get("execute") is True or str(request.args.get("execute")).lower() == "true":
        dry_run = False
    scope = (request_json.get("asset_scope") or request.args.get("asset_scope") or "all").lower()
    if scope not in {"all", "equities", "crypto"}:
        return json.dumps({"status": "error", "message": "asset_scope must be all, equities or crypto"}), 400, {"Content-Type": "application/json"}

    try:
        from conf.conf import load_config
        from custom_function.alpaca_client import AlpacaPaperClient, is_crypto_position, normalize_symbol
        from custom_function.bq_operations import (
            ensure_positions_table,
            fetch_open_entries,
            fetch_unfinalized_orders,
            save_exit,
            save_position_snapshot,
            sync_order_status,
        )

        config = load_config()
        if config["execution_mode"] != "paper":
            raise RuntimeError("Safety guard: PAPER_EXECUTION_MODE must be paper")
        client = AlpacaPaperClient(config["alpaca_base_url"], config["alpaca_api_key"], config["alpaca_secret_key"], config["request_timeout_seconds"])
        account_status, _, account = client.get_account()
        if account_status >= 400:
            return json.dumps({"status": "error", "message": "Alpaca account check failed", "response": account}), 502, {"Content-Type": "application/json"}

        ensure_positions_table(config)
        for order in fetch_unfinalized_orders(config):
            status_code, request_id, response = client.get_order(order["alpaca_order_id"])
            sync_order_status(config, order["client_order_id"], status_code, request_id, response)

        entries = {normalize_symbol(row["alpaca_symbol"]): row for row in fetch_open_entries(config)}
        positions_status, _, positions = client.get_positions()
        if positions_status >= 400:
            return json.dumps({"status": "error", "message": "Alpaca positions check failed", "response": positions}), 502, {"Content-Type": "application/json"}

        clock = {"is_open": False}
        if scope in {"all", "equities"}:
            clock_status, _, clock_response = client.get_clock()
            if clock_status < 400 and isinstance(clock_response, dict):
                clock = clock_response

        results = []
        exits = 0
        for position in positions if isinstance(positions, list) else []:
            crypto = is_crypto_position(position)
            if (scope == "crypto" and not crypto) or (scope == "equities" and crypto):
                continue
            entry = entries.get(normalize_symbol(position.get("symbol")))
            if not entry:
                results.append({"symbol": position.get("symbol"), "status": "SKIPPED_UNMANAGED_POSITION"})
                continue
            save_position_snapshot(config, entry, position)
            if not crypto and not clock.get("is_open"):
                results.append({"symbol": position.get("symbol"), "status": "SKIPPED_MARKET_CLOSED"})
                continue
            current_price = float(position.get("current_price") or 0)
            stop_loss = float(entry.get("stop_loss") or 0)
            take_profit = float(entry.get("take_profit_1") or 0)
            reason = "STOP_LOSS" if stop_loss and current_price <= stop_loss else "TAKE_PROFIT_1" if take_profit and current_price >= take_profit else None
            if not reason:
                results.append({"symbol": position.get("symbol"), "status": "HEALTHY", "current_price": current_price})
                continue
            if exits >= config["max_exits_per_run"]:
                results.append({"symbol": position.get("symbol"), "status": "SKIPPED_EXIT_LIMIT"})
                continue
            client_order_id = f"flsm-exit-{entry['paper_trade_id'][:38]}-{reason.lower()}".lower()
            payload = {"symbol": position["symbol"], "side": "sell", "type": "market", "time_in_force": "gtc" if crypto else "day", "qty": str(abs(float(position.get("qty") or 0))), "client_order_id": client_order_id}
            if dry_run:
                status_code, request_id, response = 0, None, {"dry_run": True}
            else:
                status_code, request_id, response = client.create_order(payload)
            save_exit(config, entry, position, reason, payload, status_code, request_id, response, dry_run)
            results.append({"symbol": position.get("symbol"), "reason": reason, "status": "DRY_RUN" if dry_run else ("SUBMITTED" if 200 <= status_code < 300 else "ERROR")})
            exits += 1
        return json.dumps({"status": "dry_run" if dry_run else "processed", "asset_scope": scope, "positions_checked": len(positions or []), "results": results}), 200, {"Content-Type": "application/json"}
    except Exception as exc:
        logging.exception("Paper trade risk monitor failed")
        return json.dumps({"status": "error", "message": str(exc)}), 500, {"Content-Type": "application/json"}


if __name__ == "__main__":
    from functions_framework import create_app
    app = create_app("main")
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

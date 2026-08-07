import json
import logging
import os
import sys
from datetime import datetime

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


def _round_price(value):
    if value is None:
        return None
    return str(round(float(value), 2))


def _build_client_order_id(signal):
    return f"flsm-{signal['paper_trade_id'][:48]}".lower()


def _notional_usd(signal, config):
    suggested = float(signal.get("position_notional_clp") or 0) / float(signal.get("usd_clp_assumption") or 950)
    if suggested <= 0:
        suggested = config["max_notional_usd"]
    return round(min(suggested, config["max_notional_usd"]), 2)


def _build_order_payload(signal, config, alpaca_symbol, is_crypto):
    notional_usd = _notional_usd(signal, config)
    payload = {
        "symbol": alpaca_symbol,
        "side": "buy",
        "type": "market",
        "time_in_force": "gtc" if is_crypto else "day",
        "client_order_id": _build_client_order_id(signal),
        "notional": str(notional_usd),
    }

    if not is_crypto and config["equity_order_class"] == "bracket":
        entry = float(signal["theoretical_entry_price"])
        qty = max(round(notional_usd / entry, 6), 0.000001)
        payload.pop("notional", None)
        payload["qty"] = str(qty)
        payload["order_class"] = "bracket"
        payload["take_profit"] = {"limit_price": _round_price(signal.get("take_profit_1"))}
        payload["stop_loss"] = {"stop_price": _round_price(signal.get("stop_loss"))}

    return payload, notional_usd, float(payload["qty"]) if "qty" in payload else None


def main(request):
    request_json = request.get_json(silent=True) or {}
    dry_run = parse_bool(request_json.get("dry_run", request.args.get("dry_run")), True)
    analysis_date = parse_date(request_json.get("analysis_date") or request.args.get("analysis_date"))
    max_orders = int(request_json.get("max_orders") or request.args.get("max_orders") or 0)
    asset_scope = (request_json.get("asset_scope") or request.args.get("asset_scope") or "all").lower()
    if asset_scope not in {"all", "equities", "crypto"}:
        return json.dumps({"status": "error", "message": "asset_scope must be all, equities or crypto"}), 400, {"Content-Type": "application/json"}

    try:
        if request_json.get("execute") is True or str(request.args.get("execute")).lower() == "true":
            dry_run = False

        config = load_config()
        if config["execution_mode"] != "paper":
            raise RuntimeError("Safety guard: PAPER_EXECUTION_MODE must be 'paper'")

        from custom_function.alpaca_client import AlpacaPaperClient, is_crypto_ticker, to_alpaca_symbol
        from custom_function.bq_operations import count_submitted_today, ensure_executions_table, fetch_entry_candidates, save_execution

        ensure_executions_table(config)

        client = AlpacaPaperClient(
            config["alpaca_base_url"],
            config["alpaca_api_key"],
            config["alpaca_secret_key"],
            timeout_seconds=config["request_timeout_seconds"],
        )
        account_status, account_request_id, account = client.get_account()
        if account_status >= 400:
            return (
                json.dumps(
                    {
                        "status": "error",
                        "message": "Alpaca account check failed",
                        "http_status": account_status,
                        "request_id": account_request_id,
                        "response": account,
                    },
                    default=str,
                ),
                502,
                {"Content-Type": "application/json"},
            )

        positions_status, _, positions = client.get_positions()
        open_symbols = set()
        if positions_status < 400 and isinstance(positions, list):
            open_symbols = {str(pos.get("symbol")) for pos in positions if float(pos.get("qty") or 0) != 0}
        if len(open_symbols) >= config["max_open_positions"]:
            return (
                json.dumps(
                    {
                        "status": "skipped_risk_limit",
                        "message": "Max open positions reached",
                        "open_positions": sorted(open_symbols),
                    },
                    default=str,
                ),
                200,
                {"Content-Type": "application/json"},
            )

        candidate_limit = max_orders or config["max_orders_per_run"]
        candidates = fetch_entry_candidates(config, analysis_date, limit=candidate_limit * 3, asset_scope=asset_scope)
        if not candidates:
            return json.dumps({"status": "no_candidates"}), 200, {"Content-Type": "application/json"}

        run_results = []
        first_date = candidates[0]["analysis_date"]
        submitted_today = count_submitted_today(config, first_date)
        remaining_today = max(config["max_orders_per_day"] - submitted_today, 0)
        remaining_run = min(candidate_limit, remaining_today)

        if remaining_run <= 0:
            return (
                json.dumps(
                    {
                        "status": "skipped_risk_limit",
                        "message": "Daily order limit reached",
                        "analysis_date": str(first_date),
                        "asset_scope": asset_scope,
                        "submitted_today": submitted_today,
                    },
                    default=str,
                ),
                200,
                {"Content-Type": "application/json"},
            )

        for signal in candidates:
            if len([r for r in run_results if r.get("execution_status") == "SUBMITTED"]) >= remaining_run:
                break

            alpaca_symbol = to_alpaca_symbol(signal["ticker"])
            crypto = is_crypto_ticker(signal["ticker"], signal.get("asset_type"))
            if crypto and not config["enable_crypto_orders"]:
                run_results.append({"ticker": signal["ticker"], "execution_status": "SKIPPED_CRYPTO_DISABLED"})
                continue
            if alpaca_symbol in open_symbols:
                run_results.append({"ticker": signal["ticker"], "execution_status": "SKIPPED_EXISTING_POSITION"})
                continue

            payload, notional_usd, qty = _build_order_payload(signal, config, alpaca_symbol, crypto)
            record = {
                "analysis_date": signal.get("analysis_date"),
                "signal_timestamp": signal.get("signal_timestamp"),
                "paper_trade_id": signal.get("paper_trade_id"),
                "ticker": signal.get("ticker"),
                "alpaca_symbol": alpaca_symbol,
                "asset_type": signal.get("asset_type"),
                "strategy_version": signal.get("strategy_version"),
                "order_intent": "ENTRY",
                "client_order_id": payload["client_order_id"],
                "broker_environment": "alpaca_paper",
                "order_side": "buy",
                "order_type": payload["type"],
                "time_in_force": payload["time_in_force"],
                "order_class": payload.get("order_class", "simple"),
                "notional_usd": notional_usd,
                "qty": qty,
                "theoretical_entry_price": float(signal.get("theoretical_entry_price") or 0),
                "stop_loss": float(signal.get("stop_loss") or 0),
                "take_profit_1": float(signal.get("take_profit_1") or 0),
                "max_holding_days": int(signal.get("max_holding_days") or 0) or None,
                "setup_score": float(signal.get("setup_score") or 0),
                "signal_reason": signal.get("signal_reason"),
                "order_payload": payload,
            }

            if dry_run:
                record.update(
                    {
                        "execution_status": "DRY_RUN",
                        "order_status": "not_submitted",
                        "http_status": 0,
                        "order_response": {"dry_run": True},
                    }
                )
                run_results.append({**record, "order_payload": payload})
                continue

            status_code, request_id, response = client.create_order(payload)
            accepted = 200 <= status_code < 300
            record.update(
                {
                    "alpaca_order_id": response.get("id") if isinstance(response, dict) else None,
                    "order_status": response.get("status") if isinstance(response, dict) else None,
                    "request_id": request_id,
                    "http_status": status_code,
                    "execution_status": "SUBMITTED" if accepted else "ERROR",
                    "error_message": None if accepted else json.dumps(response, ensure_ascii=True, default=str)[:1000],
                    "order_response": response,
                }
            )
            save_execution(config, record)
            run_results.append(
                {
                    "ticker": record["ticker"],
                    "client_order_id": record["client_order_id"],
                    "alpaca_order_id": record["alpaca_order_id"],
                    "execution_status": record["execution_status"],
                    "http_status": status_code,
                    "request_id": request_id,
                }
            )
            if accepted:
                open_symbols.add(alpaca_symbol)

        return (
            json.dumps(
                {
                    "status": "dry_run" if dry_run else "processed",
                    "analysis_date": str(first_date),
                    "asset_scope": asset_scope,
                    "candidate_count": len(candidates),
                    "submitted_today_before_run": submitted_today,
                    "max_orders_this_run": remaining_run,
                    "results": run_results,
                },
                default=str,
            ),
            200,
            {"Content-Type": "application/json"},
        )
    except Exception as exc:
        logging.exception("Alpaca paper trade executor failed")
        return json.dumps({"status": "error", "message": str(exc)}), 500, {"Content-Type": "application/json"}


if __name__ == "__main__":
    from functions_framework import create_app

    port = int(os.environ.get("PORT", 8080))
    app = create_app("main")
    app.run(host="0.0.0.0", port=port)

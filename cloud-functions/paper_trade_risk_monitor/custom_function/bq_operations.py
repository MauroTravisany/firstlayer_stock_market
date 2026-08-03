import json
from datetime import datetime, timezone

from google.cloud import bigquery


def _table_ref(table):
    return f"`{table}`"


def fetch_open_entries(config):
    query = f"""
    WITH entries AS (
      SELECT *, ROW_NUMBER() OVER (PARTITION BY alpaca_symbol ORDER BY updated_at DESC) AS rn
      FROM {_table_ref(config['executions_table'])}
      WHERE order_intent = "ENTRY"
        AND execution_status IN ("SUBMITTED", "FILLED", "ACCEPTED", "PENDING")
    ), exits AS (
      SELECT DISTINCT paper_trade_id
      FROM {_table_ref(config['executions_table'])}
      WHERE order_intent = "EXIT"
        AND execution_status IN ("SUBMITTED", "FILLED", "ACCEPTED", "PENDING")
    )
    SELECT * EXCEPT (rn)
    FROM entries
    WHERE rn = 1 AND paper_trade_id NOT IN (SELECT paper_trade_id FROM exits)
    """
    return [dict(row) for row in bigquery.Client(project=config["project_id"]).query(query).result()]


def save_exit(config, entry, position, reason, payload, status_code, request_id, response, dry_run):
    now = datetime.now(timezone.utc)
    client_order_id = payload["client_order_id"]
    query = f"""
    MERGE {_table_ref(config['executions_table'])} T
    USING (SELECT @client_order_id AS client_order_id) S
    ON T.client_order_id = S.client_order_id
    WHEN NOT MATCHED THEN INSERT (
      analysis_date, signal_timestamp, paper_trade_id, ticker, alpaca_symbol, asset_type, strategy_version,
      order_intent, client_order_id, alpaca_order_id, broker_environment, order_status, order_side, order_type,
      time_in_force, order_class, notional_usd, qty, theoretical_entry_price, stop_loss, take_profit_1,
      setup_score, signal_reason, request_id, http_status, execution_status, error_message,
      order_payload_json, order_response_json, created_at, updated_at
    ) VALUES (
      @analysis_date, @signal_timestamp, @paper_trade_id, @ticker, @alpaca_symbol, @asset_type, @strategy_version,
      "EXIT", @client_order_id, @alpaca_order_id, "alpaca_paper", @order_status, "sell", "market",
      @time_in_force, "simple", @notional_usd, @qty, @theoretical_entry_price, @stop_loss, @take_profit_1,
      @setup_score, @signal_reason, @request_id, @http_status, @execution_status, @error_message,
      @order_payload_json, @order_response_json, @created_at, @updated_at
    )
    """
    accepted = 200 <= status_code < 300
    params = [
        bigquery.ScalarQueryParameter("analysis_date", "DATE", entry["analysis_date"]),
        bigquery.ScalarQueryParameter("signal_timestamp", "DATETIME", entry.get("signal_timestamp")),
        bigquery.ScalarQueryParameter("paper_trade_id", "STRING", entry["paper_trade_id"]),
        bigquery.ScalarQueryParameter("ticker", "STRING", entry["ticker"]),
        bigquery.ScalarQueryParameter("alpaca_symbol", "STRING", entry["alpaca_symbol"]),
        bigquery.ScalarQueryParameter("asset_type", "STRING", entry.get("asset_type")),
        bigquery.ScalarQueryParameter("strategy_version", "STRING", entry.get("strategy_version")),
        bigquery.ScalarQueryParameter("client_order_id", "STRING", client_order_id),
        bigquery.ScalarQueryParameter("alpaca_order_id", "STRING", response.get("id") if isinstance(response, dict) else None),
        bigquery.ScalarQueryParameter("order_status", "STRING", "not_submitted" if dry_run else (response.get("status") if isinstance(response, dict) else None)),
        bigquery.ScalarQueryParameter("time_in_force", "STRING", payload["time_in_force"]),
        bigquery.ScalarQueryParameter("notional_usd", "FLOAT64", float(position.get("market_value") or 0)),
        bigquery.ScalarQueryParameter("qty", "FLOAT64", float(position.get("qty") or 0)),
        bigquery.ScalarQueryParameter("theoretical_entry_price", "FLOAT64", float(entry.get("theoretical_entry_price") or 0)),
        bigquery.ScalarQueryParameter("stop_loss", "FLOAT64", float(entry.get("stop_loss") or 0)),
        bigquery.ScalarQueryParameter("take_profit_1", "FLOAT64", float(entry.get("take_profit_1") or 0)),
        bigquery.ScalarQueryParameter("setup_score", "FLOAT64", float(entry.get("setup_score") or 0)),
        bigquery.ScalarQueryParameter("signal_reason", "STRING", f"Salida automatica por {reason}; precio_actual={position.get('current_price')}"),
        bigquery.ScalarQueryParameter("request_id", "STRING", request_id),
        bigquery.ScalarQueryParameter("http_status", "INT64", status_code),
        bigquery.ScalarQueryParameter("execution_status", "STRING", "DRY_RUN" if dry_run else ("SUBMITTED" if accepted else "ERROR")),
        bigquery.ScalarQueryParameter("error_message", "STRING", None if dry_run or accepted else json.dumps(response, ensure_ascii=True)[:2000]),
        bigquery.ScalarQueryParameter("order_payload_json", "STRING", json.dumps(payload, ensure_ascii=True)),
        bigquery.ScalarQueryParameter("order_response_json", "STRING", json.dumps(response, ensure_ascii=True, default=str)),
        bigquery.ScalarQueryParameter("created_at", "TIMESTAMP", now),
        bigquery.ScalarQueryParameter("updated_at", "TIMESTAMP", now),
    ]
    bigquery.Client(project=config["project_id"]).query(query, job_config=bigquery.QueryJobConfig(query_parameters=params)).result()

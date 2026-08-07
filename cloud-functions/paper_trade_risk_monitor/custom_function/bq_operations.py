import json
from datetime import datetime, timezone

from google.cloud import bigquery


def _table_ref(table):
    return f"`{table}`"


def fetch_open_entries(config):
    query = f"""
    WITH active_entries AS (
      SELECT e.*
      FROM {_table_ref(config['executions_table'])} e
      WHERE e.order_intent = "ENTRY"
        AND e.execution_status IN ("SUBMITTED", "FILLED", "ACCEPTED", "PENDING")
        AND NOT EXISTS (
          SELECT 1
          FROM {_table_ref(config['executions_table'])} x
          WHERE x.order_intent = "EXIT"
            AND x.execution_status IN ("SUBMITTED", "FILLED", "ACCEPTED", "PENDING")
            AND x.alpaca_symbol = e.alpaca_symbol
            AND x.created_at >= e.created_at
        )
    ), grouped AS (
      SELECT
        ARRAY_AGG(e ORDER BY e.updated_at DESC LIMIT 1)[OFFSET(0)] AS entry,
        COUNT(*) AS active_entry_count,
        MAX(e.stop_loss) AS consolidated_stop_loss,
        MIN(e.take_profit_1) AS consolidated_take_profit_1,
        MIN(e.analysis_date) AS oldest_analysis_date,
        MIN(e.max_holding_days) AS consolidated_max_holding_days
      FROM active_entries e
      GROUP BY e.alpaca_symbol
    )
    SELECT
      entry.*,
      active_entry_count,
      consolidated_stop_loss,
      consolidated_take_profit_1,
      oldest_analysis_date,
      consolidated_max_holding_days
    FROM grouped
    """
    return [dict(row) for row in bigquery.Client(project=config["project_id"]).query(query).result()]


def count_observed_sessions(config, ticker, entry_date):
    if not entry_date:
        return 0
    query = f"""
    SELECT COUNT(DISTINCT fecha) AS observed_sessions
    FROM {_table_ref(config['prices_table'])}
    WHERE ticker = @ticker
      AND fecha > @entry_date
      AND fecha <= CURRENT_DATE("America/New_York")
    """
    params = [
        bigquery.ScalarQueryParameter("ticker", "STRING", ticker),
        bigquery.ScalarQueryParameter("entry_date", "DATE", entry_date),
    ]
    rows = list(
        bigquery.Client(project=config["project_id"]).query(
            query, job_config=bigquery.QueryJobConfig(query_parameters=params)
        ).result()
    )
    return int(rows[0]["observed_sessions"] or 0) if rows else 0


def ensure_positions_table(config):
    query = f"""
    CREATE TABLE IF NOT EXISTS {_table_ref(config['positions_table'])} (
      snapshot_date DATE NOT NULL,
      snapshot_at TIMESTAMP NOT NULL,
      paper_trade_id STRING NOT NULL,
      ticker STRING NOT NULL,
      alpaca_symbol STRING NOT NULL,
      asset_type STRING,
      strategy_version STRING,
      side STRING,
      quantity FLOAT64,
      avg_entry_price FLOAT64,
      current_price FLOAT64,
      market_value_usd FLOAT64,
      cost_basis_usd FLOAT64,
      unrealized_pl_usd FLOAT64,
      unrealized_plpc FLOAT64,
      position_status STRING NOT NULL
    )
    PARTITION BY snapshot_date
    CLUSTER BY ticker, paper_trade_id
    """
    bigquery.Client(project=config["project_id"]).query(query).result()


def fetch_unfinalized_orders(config, limit=12):
    query = f"""
    SELECT client_order_id, alpaca_order_id
    FROM {_table_ref(config['executions_table'])}
    WHERE alpaca_order_id IS NOT NULL
      AND execution_status IN ("SUBMITTED", "PENDING", "ACCEPTED")
    ORDER BY updated_at ASC
    LIMIT @limit
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("limit", "INT64", limit)]
    )
    return [dict(row) for row in bigquery.Client(project=config["project_id"]).query(query, job_config=job_config).result()]


def sync_order_status(config, client_order_id, status_code, request_id, response):
    order_status = response.get("status") if isinstance(response, dict) else None
    normalized = str(order_status or "unknown").upper()
    if status_code >= 400:
        execution_status = "ERROR"
    elif normalized == "FILLED":
        execution_status = "FILLED"
    elif normalized in {"CANCELED", "CANCELLED", "EXPIRED", "REJECTED", "SUSPENDED"}:
        execution_status = normalized
    else:
        execution_status = "PENDING"
    query = f"""
    UPDATE {_table_ref(config['executions_table'])}
    SET order_status = @order_status,
        execution_status = @execution_status,
        request_id = COALESCE(@request_id, request_id),
        http_status = @http_status,
        error_message = IF(@http_status >= 400, @response_json, NULL),
        order_response_json = @response_json,
        updated_at = CURRENT_TIMESTAMP()
    WHERE client_order_id = @client_order_id
    """
    params = [
        bigquery.ScalarQueryParameter("order_status", "STRING", order_status),
        bigquery.ScalarQueryParameter("execution_status", "STRING", execution_status),
        bigquery.ScalarQueryParameter("request_id", "STRING", request_id),
        bigquery.ScalarQueryParameter("http_status", "INT64", status_code),
        bigquery.ScalarQueryParameter("response_json", "STRING", json.dumps(response, ensure_ascii=True, default=str)[:50000]),
        bigquery.ScalarQueryParameter("client_order_id", "STRING", client_order_id),
    ]
    bigquery.Client(project=config["project_id"]).query(query, job_config=bigquery.QueryJobConfig(query_parameters=params)).result()
    return execution_status


def save_position_snapshot(config, entry, position):
    now = datetime.now(timezone.utc)

    def number(value):
        try:
            return float(value) if value not in (None, "") else None
        except (TypeError, ValueError):
            return None

    query = f"""
    INSERT INTO {_table_ref(config['positions_table'])} (
      snapshot_date, snapshot_at, paper_trade_id, ticker, alpaca_symbol, asset_type,
      strategy_version, side, quantity, avg_entry_price, current_price, market_value_usd,
      cost_basis_usd, unrealized_pl_usd, unrealized_plpc, position_status
    ) VALUES (
      @snapshot_date, @snapshot_at, @paper_trade_id, @ticker, @alpaca_symbol, @asset_type,
      @strategy_version, @side, @quantity, @avg_entry_price, @current_price, @market_value_usd,
      @cost_basis_usd, @unrealized_pl_usd, @unrealized_plpc, "OPEN"
    )
    """
    params = [
        bigquery.ScalarQueryParameter("snapshot_date", "DATE", now.date()),
        bigquery.ScalarQueryParameter("snapshot_at", "TIMESTAMP", now),
        bigquery.ScalarQueryParameter("paper_trade_id", "STRING", entry["paper_trade_id"]),
        bigquery.ScalarQueryParameter("ticker", "STRING", entry["ticker"]),
        bigquery.ScalarQueryParameter("alpaca_symbol", "STRING", entry["alpaca_symbol"]),
        bigquery.ScalarQueryParameter("asset_type", "STRING", entry.get("asset_type")),
        bigquery.ScalarQueryParameter("strategy_version", "STRING", entry.get("strategy_version")),
        bigquery.ScalarQueryParameter("side", "STRING", position.get("side")),
        bigquery.ScalarQueryParameter("quantity", "FLOAT64", number(position.get("qty"))),
        bigquery.ScalarQueryParameter("avg_entry_price", "FLOAT64", number(position.get("avg_entry_price"))),
        bigquery.ScalarQueryParameter("current_price", "FLOAT64", number(position.get("current_price"))),
        bigquery.ScalarQueryParameter("market_value_usd", "FLOAT64", number(position.get("market_value"))),
        bigquery.ScalarQueryParameter("cost_basis_usd", "FLOAT64", number(position.get("cost_basis"))),
        bigquery.ScalarQueryParameter("unrealized_pl_usd", "FLOAT64", number(position.get("unrealized_pl"))),
        bigquery.ScalarQueryParameter("unrealized_plpc", "FLOAT64", number(position.get("unrealized_plpc"))),
    ]
    bigquery.Client(project=config["project_id"]).query(query, job_config=bigquery.QueryJobConfig(query_parameters=params)).result()


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
      max_holding_days, setup_score, signal_reason, request_id, http_status, execution_status, error_message,
      order_payload_json, order_response_json, created_at, updated_at
    ) VALUES (
      @analysis_date, @signal_timestamp, @paper_trade_id, @ticker, @alpaca_symbol, @asset_type, @strategy_version,
      "EXIT", @client_order_id, @alpaca_order_id, "alpaca_paper", @order_status, "sell", "market",
      @time_in_force, "simple", @notional_usd, @qty, @theoretical_entry_price, @stop_loss, @take_profit_1,
      @max_holding_days, @setup_score, @signal_reason, @request_id, @http_status, @execution_status, @error_message,
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
        bigquery.ScalarQueryParameter("max_holding_days", "INT64", entry.get("max_holding_days")),
        bigquery.ScalarQueryParameter("setup_score", "FLOAT64", float(entry.get("setup_score") or 0)),
        bigquery.ScalarQueryParameter(
            "signal_reason",
            "STRING",
            f"Salida automatica por {reason}; precio_actual={position.get('current_price')}; "
            f"entradas_consolidadas={entry.get('active_entry_count', 1)}",
        ),
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

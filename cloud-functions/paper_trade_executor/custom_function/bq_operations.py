import json
from datetime import datetime

from google.cloud import bigquery


def _table_ref(table):
    return f"`{table}`"


def json_dumps(value):
    return json.dumps(value, ensure_ascii=True, default=str)


def ensure_executions_table(config):
    client = bigquery.Client(project=config["project_id"])
    query = f"""
    CREATE TABLE IF NOT EXISTS {_table_ref(config["executions_table"])} (
      analysis_date DATE NOT NULL,
      signal_timestamp DATETIME,
      paper_trade_id STRING NOT NULL,
      ticker STRING NOT NULL,
      alpaca_symbol STRING NOT NULL,
      asset_type STRING,
      strategy_version STRING,
      order_intent STRING NOT NULL,
      client_order_id STRING NOT NULL,
      alpaca_order_id STRING,
      broker_environment STRING NOT NULL,
      order_status STRING,
      order_side STRING,
      order_type STRING,
      time_in_force STRING,
      order_class STRING,
      notional_usd FLOAT64,
      qty FLOAT64,
      theoretical_entry_price FLOAT64,
      stop_loss FLOAT64,
      take_profit_1 FLOAT64,
      setup_score FLOAT64,
      signal_reason STRING,
      request_id STRING,
      http_status INT64,
      execution_status STRING NOT NULL,
      error_message STRING,
      order_payload_json STRING,
      order_response_json STRING,
      created_at TIMESTAMP NOT NULL,
      updated_at TIMESTAMP NOT NULL
    )
    PARTITION BY analysis_date
    CLUSTER BY ticker, execution_status, client_order_id
    """
    client.query(query).result()


def count_submitted_today(config, analysis_date):
    client = bigquery.Client(project=config["project_id"])
    query = f"""
    SELECT COUNT(*) AS submitted_count
    FROM {_table_ref(config["executions_table"])}
    WHERE analysis_date = @analysis_date
      AND order_intent = "ENTRY"
      AND execution_status IN ("SUBMITTED", "FILLED", "ACCEPTED", "PENDING")
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("analysis_date", "DATE", analysis_date)]
    )
    rows = list(client.query(query, job_config=job_config).result())
    return int(rows[0]["submitted_count"]) if rows else 0


def fetch_entry_candidates(config, analysis_date=None, limit=10, asset_scope="all"):
    client = bigquery.Client(project=config["project_id"])
    date_filter = "analysis_date = @analysis_date" if analysis_date else "analysis_date = (SELECT MAX(analysis_date) FROM " + _table_ref(config["signals_table"]) + ")"
    query = f"""
    WITH latest_slot AS (
      SELECT analysis_date, MAX(signal_hour) AS signal_hour
      FROM {_table_ref(config["signals_table"])}
      WHERE {date_filter}
      GROUP BY analysis_date
    ),
    already_executed AS (
      SELECT DISTINCT paper_trade_id
      FROM {_table_ref(config["executions_table"])}
      WHERE order_intent = "ENTRY"
        AND execution_status IN ("SUBMITTED", "FILLED", "ACCEPTED", "PENDING")
    )
    SELECT
      s.analysis_date,
      s.signal_hour,
      s.signal_timestamp,
      s.paper_trade_id,
      s.ticker,
      s.asset_type,
      s.strategy_version,
      s.strategy_name,
      s.paper_signal,
      s.setup_score,
      s.theoretical_entry_price,
      s.stop_loss,
      s.take_profit_1,
      s.position_notional_clp,
      s.theoretical_quantity,
      s.usd_clp_assumption,
      s.signal_reason
    FROM {_table_ref(config["signals_table"])} s
    JOIN latest_slot ls
      ON ls.analysis_date = s.analysis_date
     AND ls.signal_hour = s.signal_hour
    LEFT JOIN already_executed ae
      ON ae.paper_trade_id = s.paper_trade_id
    WHERE s.paper_signal = "TRADE_LONG"
      AND s.execution_eligible = TRUE
      AND s.setup_score >= @min_setup_score
      AND ae.paper_trade_id IS NULL
      AND (
        @asset_scope = "all"
        OR (@asset_scope = "crypto" AND s.asset_type = "CRYPTO")
        OR (@asset_scope = "equities" AND s.asset_type != "CRYPTO")
      )
    ORDER BY s.setup_score DESC, s.ticker, s.strategy_version
    LIMIT @limit
    """
    params = [
        bigquery.ScalarQueryParameter("min_setup_score", "FLOAT64", config["min_setup_score"]),
        bigquery.ScalarQueryParameter("limit", "INT64", limit),
        bigquery.ScalarQueryParameter("asset_scope", "STRING", asset_scope),
    ]
    if analysis_date:
        params.append(bigquery.ScalarQueryParameter("analysis_date", "DATE", analysis_date))
    job_config = bigquery.QueryJobConfig(query_parameters=params)
    return [dict(row) for row in client.query(query, job_config=job_config).result()]


def save_execution(config, record):
    client = bigquery.Client(project=config["project_id"])
    query = f"""
    MERGE {_table_ref(config["executions_table"])} T
    USING (
      SELECT
        @analysis_date AS analysis_date,
        @signal_timestamp AS signal_timestamp,
        @paper_trade_id AS paper_trade_id,
        @ticker AS ticker,
        @alpaca_symbol AS alpaca_symbol,
        @asset_type AS asset_type,
        @strategy_version AS strategy_version,
        @order_intent AS order_intent,
        @client_order_id AS client_order_id,
        @alpaca_order_id AS alpaca_order_id,
        @broker_environment AS broker_environment,
        @order_status AS order_status,
        @order_side AS order_side,
        @order_type AS order_type,
        @time_in_force AS time_in_force,
        @order_class AS order_class,
        @notional_usd AS notional_usd,
        @qty AS qty,
        @theoretical_entry_price AS theoretical_entry_price,
        @stop_loss AS stop_loss,
        @take_profit_1 AS take_profit_1,
        @setup_score AS setup_score,
        @signal_reason AS signal_reason,
        @request_id AS request_id,
        @http_status AS http_status,
        @execution_status AS execution_status,
        @error_message AS error_message,
        @order_payload_json AS order_payload_json,
        @order_response_json AS order_response_json,
        CURRENT_TIMESTAMP() AS touched_at
    ) S
    ON T.client_order_id = S.client_order_id
    WHEN MATCHED THEN UPDATE SET
      alpaca_order_id = S.alpaca_order_id,
      order_status = S.order_status,
      request_id = S.request_id,
      http_status = S.http_status,
      execution_status = S.execution_status,
      error_message = S.error_message,
      order_response_json = S.order_response_json,
      updated_at = S.touched_at
    WHEN NOT MATCHED THEN INSERT (
      analysis_date, signal_timestamp, paper_trade_id, ticker, alpaca_symbol, asset_type,
      strategy_version, order_intent, client_order_id, alpaca_order_id, broker_environment,
      order_status, order_side, order_type, time_in_force, order_class, notional_usd, qty,
      theoretical_entry_price, stop_loss, take_profit_1, setup_score, signal_reason,
      request_id, http_status, execution_status, error_message, order_payload_json,
      order_response_json, created_at, updated_at
    ) VALUES (
      S.analysis_date, S.signal_timestamp, S.paper_trade_id, S.ticker, S.alpaca_symbol, S.asset_type,
      S.strategy_version, S.order_intent, S.client_order_id, S.alpaca_order_id, S.broker_environment,
      S.order_status, S.order_side, S.order_type, S.time_in_force, S.order_class, S.notional_usd, S.qty,
      S.theoretical_entry_price, S.stop_loss, S.take_profit_1, S.setup_score, S.signal_reason,
      S.request_id, S.http_status, S.execution_status, S.error_message, S.order_payload_json,
      S.order_response_json, S.touched_at, S.touched_at
    )
    """
    params = [
        bigquery.ScalarQueryParameter("analysis_date", "DATE", record.get("analysis_date")),
        bigquery.ScalarQueryParameter("signal_timestamp", "DATETIME", record.get("signal_timestamp")),
        bigquery.ScalarQueryParameter("paper_trade_id", "STRING", record.get("paper_trade_id")),
        bigquery.ScalarQueryParameter("ticker", "STRING", record.get("ticker")),
        bigquery.ScalarQueryParameter("alpaca_symbol", "STRING", record.get("alpaca_symbol")),
        bigquery.ScalarQueryParameter("asset_type", "STRING", record.get("asset_type")),
        bigquery.ScalarQueryParameter("strategy_version", "STRING", record.get("strategy_version")),
        bigquery.ScalarQueryParameter("order_intent", "STRING", record.get("order_intent", "ENTRY")),
        bigquery.ScalarQueryParameter("client_order_id", "STRING", record.get("client_order_id")),
        bigquery.ScalarQueryParameter("alpaca_order_id", "STRING", record.get("alpaca_order_id")),
        bigquery.ScalarQueryParameter("broker_environment", "STRING", record.get("broker_environment", "alpaca_paper")),
        bigquery.ScalarQueryParameter("order_status", "STRING", record.get("order_status")),
        bigquery.ScalarQueryParameter("order_side", "STRING", record.get("order_side", "buy")),
        bigquery.ScalarQueryParameter("order_type", "STRING", record.get("order_type", "market")),
        bigquery.ScalarQueryParameter("time_in_force", "STRING", record.get("time_in_force")),
        bigquery.ScalarQueryParameter("order_class", "STRING", record.get("order_class")),
        bigquery.ScalarQueryParameter("notional_usd", "FLOAT64", record.get("notional_usd")),
        bigquery.ScalarQueryParameter("qty", "FLOAT64", record.get("qty")),
        bigquery.ScalarQueryParameter("theoretical_entry_price", "FLOAT64", record.get("theoretical_entry_price")),
        bigquery.ScalarQueryParameter("stop_loss", "FLOAT64", record.get("stop_loss")),
        bigquery.ScalarQueryParameter("take_profit_1", "FLOAT64", record.get("take_profit_1")),
        bigquery.ScalarQueryParameter("setup_score", "FLOAT64", record.get("setup_score")),
        bigquery.ScalarQueryParameter("signal_reason", "STRING", str(record.get("signal_reason") or "")[:10000]),
        bigquery.ScalarQueryParameter("request_id", "STRING", record.get("request_id")),
        bigquery.ScalarQueryParameter("http_status", "INT64", record.get("http_status")),
        bigquery.ScalarQueryParameter("execution_status", "STRING", record.get("execution_status")),
        bigquery.ScalarQueryParameter("error_message", "STRING", str(record.get("error_message") or "")[:2000]),
        bigquery.ScalarQueryParameter("order_payload_json", "STRING", json_dumps(record.get("order_payload"))[:20000]),
        bigquery.ScalarQueryParameter("order_response_json", "STRING", json_dumps(record.get("order_response"))[:50000]),
    ]
    client.query(query, job_config=bigquery.QueryJobConfig(query_parameters=params)).result()


def normalize_date(value):
    if isinstance(value, datetime):
        return value.date()
    return value

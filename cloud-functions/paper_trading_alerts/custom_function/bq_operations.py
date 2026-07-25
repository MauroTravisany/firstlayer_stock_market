from google.cloud import bigquery


def _table_ref(table):
    return f"`{table}`"


def ensure_alerts_table(config):
    client = bigquery.Client(project=config["project_id"])
    query = f"""
    CREATE TABLE IF NOT EXISTS {_table_ref(config["alerts_table"])} (
      alert_date DATE NOT NULL,
      alert_type STRING NOT NULL,
      sent_at TIMESTAMP NOT NULL,
      status STRING,
      message STRING
    )
    PARTITION BY alert_date
    CLUSTER BY alert_type
    """
    client.query(query).result()


def already_sent(config, alert_date, alert_type):
    client = bigquery.Client(project=config["project_id"])
    query = f"""
    SELECT COUNT(*) AS sent_count
    FROM {_table_ref(config["alerts_table"])}
    WHERE alert_date = @alert_date
      AND alert_type = @alert_type
      AND status = "SENT"
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("alert_date", "DATE", alert_date),
            bigquery.ScalarQueryParameter("alert_type", "STRING", alert_type),
        ]
    )
    rows = list(client.query(query, job_config=job_config).result())
    return rows[0]["sent_count"] > 0


def mark_sent(config, alert_date, alert_type, status, message):
    client = bigquery.Client(project=config["project_id"])
    query = f"""
    MERGE {_table_ref(config["alerts_table"])} T
    USING (
      SELECT
        @alert_date AS alert_date,
        @alert_type AS alert_type,
        CURRENT_TIMESTAMP() AS sent_at,
        @status AS status,
        @message AS message
    ) S
    ON T.alert_date = S.alert_date
   AND T.alert_type = S.alert_type
    WHEN MATCHED THEN
      UPDATE SET sent_at = S.sent_at, status = S.status, message = S.message
    WHEN NOT MATCHED THEN
      INSERT (alert_date, alert_type, sent_at, status, message)
      VALUES (S.alert_date, S.alert_type, S.sent_at, S.status, S.message)
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("alert_date", "DATE", alert_date),
            bigquery.ScalarQueryParameter("alert_type", "STRING", alert_type),
            bigquery.ScalarQueryParameter("status", "STRING", status),
            bigquery.ScalarQueryParameter("message", "STRING", message[:1000]),
        ]
    )
    client.query(query, job_config=job_config).result()


def fetch_summary(config, summary_date=None):
    client = bigquery.Client(project=config["project_id"])
    date_filter = "summary_date = @summary_date" if summary_date else "summary_date = (SELECT MAX(summary_date) FROM " + _table_ref(config["summary_table"]) + ")"
    query = f"""
    SELECT *
    FROM {_table_ref(config["summary_table"])}
    WHERE {date_filter}
    LIMIT 1
    """
    params = []
    if summary_date:
        params.append(bigquery.ScalarQueryParameter("summary_date", "DATE", summary_date))
    rows = list(client.query(query, job_config=bigquery.QueryJobConfig(query_parameters=params)).result())
    return dict(rows[0]) if rows else None


def fetch_new_trades(config, summary_date, limit=5):
    client = bigquery.Client(project=config["project_id"])
    query = f"""
    SELECT
      ticker,
      asset_type,
      setup_type,
      paper_signal,
      setup_score,
      theoretical_entry_price,
      stop_loss,
      take_profit_1,
      position_notional_clp,
      signal_reason
    FROM {_table_ref(config["signals_table"])}
    WHERE analysis_date = @summary_date
      AND paper_signal IN ("TRADE_LONG", "VIGILAR")
    ORDER BY paper_signal, setup_score DESC
    LIMIT @limit
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("summary_date", "DATE", summary_date),
            bigquery.ScalarQueryParameter("limit", "INT64", limit),
        ]
    )
    return [dict(row) for row in client.query(query, job_config=job_config).result()]


def fetch_closed_trades(config, summary_date, limit=5):
    client = bigquery.Client(project=config["project_id"])
    query = f"""
    SELECT
      ticker,
      asset_type,
      setup_type,
      trade_status,
      result_label,
      theoretical_entry_price,
      exit_price,
      net_pnl_clp,
      net_return_pct
    FROM {_table_ref(config["results_table"])}
    WHERE outcome_date = @summary_date
    ORDER BY ABS(net_pnl_clp) DESC
    LIMIT @limit
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("summary_date", "DATE", summary_date),
            bigquery.ScalarQueryParameter("limit", "INT64", limit),
        ]
    )
    return [dict(row) for row in client.query(query, job_config=job_config).result()]

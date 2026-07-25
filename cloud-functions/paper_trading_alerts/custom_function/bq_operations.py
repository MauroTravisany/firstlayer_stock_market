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


def ensure_feedback_table(config):
    client = bigquery.Client(project=config["project_id"])
    query = f"""
    CREATE TABLE IF NOT EXISTS {_table_ref(config["feedback_table"])} (
      feedback_date DATE NOT NULL,
      prompt_version STRING NOT NULL,
      model_name STRING,
      executive_summary STRING,
      what_worked STRING,
      what_failed STRING,
      risk_notes STRING,
      parameter_suggestions STRING,
      news_needed STRING,
      next_actions STRING,
      confidence_score FLOAT64,
      raw_response STRING,
      created_at TIMESTAMP NOT NULL
    )
    PARTITION BY feedback_date
    CLUSTER BY prompt_version
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
      strategy_version,
      strategy_name,
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
    ORDER BY paper_signal, setup_score DESC, strategy_version
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
      strategy_version,
      strategy_name,
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


def fetch_strategy_performance(config, limit=20):
    client = bigquery.Client(project=config["project_id"])
    query = f"""
    SELECT
      strategy_version,
      ANY_VALUE(strategy_name) AS strategy_name,
      COUNT(*) AS closed_count,
      COUNTIF(is_win) AS wins,
      COUNTIF(NOT is_win) AS losses,
      ROUND(SAFE_DIVIDE(COUNTIF(is_win), COUNT(*)) * 100, 2) AS win_rate_pct,
      ROUND(SUM(net_pnl_clp), 0) AS realized_pnl_clp,
      ROUND(AVG(net_return_pct) * 100, 2) AS avg_net_return_pct,
      COUNTIF(trade_status = "STOP_LOSS") AS stop_loss_count,
      COUNTIF(trade_status IN ("TAKE_PROFIT_1", "TAKE_PROFIT_2")) AS take_profit_count
    FROM {_table_ref(config["results_table"])}
    WHERE outcome_date IS NOT NULL
    GROUP BY strategy_version
    ORDER BY realized_pnl_clp DESC
    LIMIT @limit
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ScalarQueryParameter("limit", "INT64", limit)]
    )
    return [dict(row) for row in client.query(query, job_config=job_config).result()]


def save_feedback(config, feedback_date, feedback):
    client = bigquery.Client(project=config["project_id"])
    query = f"""
    MERGE {_table_ref(config["feedback_table"])} T
    USING (
      SELECT
        @feedback_date AS feedback_date,
        @prompt_version AS prompt_version,
        @model_name AS model_name,
        @executive_summary AS executive_summary,
        @what_worked AS what_worked,
        @what_failed AS what_failed,
        @risk_notes AS risk_notes,
        @parameter_suggestions AS parameter_suggestions,
        @news_needed AS news_needed,
        @next_actions AS next_actions,
        @confidence_score AS confidence_score,
        @raw_response AS raw_response,
        CURRENT_TIMESTAMP() AS created_at
    ) S
    ON T.feedback_date = S.feedback_date
   AND T.prompt_version = S.prompt_version
    WHEN MATCHED THEN
      UPDATE SET
        model_name = S.model_name,
        executive_summary = S.executive_summary,
        what_worked = S.what_worked,
        what_failed = S.what_failed,
        risk_notes = S.risk_notes,
        parameter_suggestions = S.parameter_suggestions,
        news_needed = S.news_needed,
        next_actions = S.next_actions,
        confidence_score = S.confidence_score,
        raw_response = S.raw_response,
        created_at = S.created_at
    WHEN NOT MATCHED THEN
      INSERT (
        feedback_date, prompt_version, model_name, executive_summary, what_worked, what_failed,
        risk_notes, parameter_suggestions, news_needed, next_actions, confidence_score, raw_response, created_at
      )
      VALUES (
        S.feedback_date, S.prompt_version, S.model_name, S.executive_summary, S.what_worked, S.what_failed,
        S.risk_notes, S.parameter_suggestions, S.news_needed, S.next_actions, S.confidence_score, S.raw_response, S.created_at
      )
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[
            bigquery.ScalarQueryParameter("feedback_date", "DATE", feedback_date),
            bigquery.ScalarQueryParameter("prompt_version", "STRING", config["prompt_version"]),
            bigquery.ScalarQueryParameter("model_name", "STRING", config["openai_model"]),
            bigquery.ScalarQueryParameter("executive_summary", "STRING", str(feedback.get("executive_summary", ""))[:5000]),
            bigquery.ScalarQueryParameter("what_worked", "STRING", str(feedback.get("what_worked", ""))[:5000]),
            bigquery.ScalarQueryParameter("what_failed", "STRING", str(feedback.get("what_failed", ""))[:5000]),
            bigquery.ScalarQueryParameter("risk_notes", "STRING", str(feedback.get("risk_notes", ""))[:5000]),
            bigquery.ScalarQueryParameter("parameter_suggestions", "STRING", str(feedback.get("parameter_suggestions", ""))[:5000]),
            bigquery.ScalarQueryParameter("news_needed", "STRING", str(feedback.get("news_needed", ""))[:5000]),
            bigquery.ScalarQueryParameter("next_actions", "STRING", str(feedback.get("next_actions", ""))[:5000]),
            bigquery.ScalarQueryParameter("confidence_score", "FLOAT64", float(feedback.get("confidence_score") or 0)),
            bigquery.ScalarQueryParameter("raw_response", "STRING", str(feedback.get("raw_response", ""))[:50000]),
        ]
    )
    client.query(query, job_config=job_config).result()

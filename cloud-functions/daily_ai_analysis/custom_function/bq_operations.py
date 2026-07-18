import json
from datetime import date

from google.cloud import bigquery


def _table_ref(table):
    return f"`{table}`"


def ensure_tables(config):
    client = bigquery.Client(project=config["project_id"])

    analysis_sql = f"""
    CREATE TABLE IF NOT EXISTS {_table_ref(config["analysis_table"])} (
      analysis_date DATE NOT NULL,
      ticker STRING NOT NULL,
      signal STRING,
      classification STRING,
      final_score FLOAT64,
      valuation_score FLOAT64,
      quality_score FLOAT64,
      momentum_score FLOAT64,
      risk_score FLOAT64,
      sell_score FLOAT64,
      sell_signal STRING,
      suggested_sell_price FLOAT64,
      ai_sell_thesis STRING,
      ai_sell_reasons STRING,
      ai_sell_price_view STRING,
      ai_sell_decision_support STRING,
      ai_summary STRING,
      ai_analysis STRING,
      ai_risks STRING,
      ai_opportunity STRING,
      ai_decision_support STRING,
      external_sources_json STRING,
      external_context_summary STRING,
      data_discrepancies STRING,
      confidence_score FLOAT64,
      confidence_reason STRING,
      model_name STRING,
      prompt_version STRING,
      input_hash STRING,
      raw_response_json STRING,
      created_at TIMESTAMP NOT NULL
    )
    PARTITION BY analysis_date
    CLUSTER BY signal, ticker
    """

    summary_sql = f"""
    CREATE TABLE IF NOT EXISTS {_table_ref(config["summary_table"])} (
      analysis_date DATE NOT NULL,
      portfolio_summary STRING,
      top_opportunities STRING,
      overvalued_summary STRING,
      risk_summary STRING,
      dashboard_summary STRING,
      alert_title STRING,
      alert_body STRING,
      alert_sent BOOL,
      alert_error STRING,
      model_name STRING,
      prompt_version STRING,
      created_at TIMESTAMP NOT NULL
    )
    PARTITION BY analysis_date
    """

    client.query(analysis_sql).result()
    client.query(summary_sql).result()

    for column_name, column_type in [
        ("sell_score", "FLOAT64"),
        ("sell_signal", "STRING"),
        ("suggested_sell_price", "FLOAT64"),
        ("ai_sell_thesis", "STRING"),
        ("ai_sell_reasons", "STRING"),
        ("ai_sell_price_view", "STRING"),
        ("ai_sell_decision_support", "STRING"),
    ]:
        client.query(
            f"ALTER TABLE {_table_ref(config['analysis_table'])} ADD COLUMN IF NOT EXISTS {column_name} {column_type}"
        ).result()


def get_analysis_date(config, requested_date=None):
    if requested_date:
        return date.fromisoformat(requested_date)

    client = bigquery.Client(project=config["project_id"])
    sql = f"SELECT MAX(analysis_date) AS analysis_date FROM {_table_ref(config['signal_table'])}"
    rows = list(client.query(sql).result())
    if not rows or rows[0]["analysis_date"] is None:
        raise RuntimeError("No analysis_date found in portfolio_daily_signal")
    return rows[0]["analysis_date"]


def fetch_daily_signals(config, analysis_date, tickers=None):
    client = bigquery.Client(project=config["project_id"])
    params = [bigquery.ScalarQueryParameter("analysis_date", "DATE", analysis_date)]
    ticker_filter = ""
    if tickers:
        ticker_filter = "AND ticker IN UNNEST(@tickers)"
        params.append(bigquery.ArrayQueryParameter("tickers", "STRING", tickers))

    sql = f"""
    SELECT
      analysis_date,
      ticker,
      last_close,
      classification,
      financial_data_status,
      valuation_score,
      value_component,
      quality_score,
      momentum_score,
      risk_score,
      sell_score,
      sell_signal,
      suggested_sell_price,
      final_score,
      return_1d,
      return_5d,
      return_20d,
      return_60d,
      volatility_20d,
      volume_vs_20d_avg,
      pe_ratio,
      forward_pe,
      price_to_sales,
      ev_to_ebitda,
      roe,
      profit_margin,
      operating_margin,
      debt_to_equity,
      current_ratio,
      free_cash_flow,
      signal,
      signal_reason,
      sell_reason
    FROM {_table_ref(config["signal_table"])}
    WHERE analysis_date = @analysis_date
    {ticker_filter}
    ORDER BY final_score DESC, ticker
    """
    job_config = bigquery.QueryJobConfig(query_parameters=params)
    return [dict(row) for row in client.query(sql, job_config=job_config).result()]


def merge_analysis(config, row):
    client = bigquery.Client(project=config["project_id"])
    sql = f"""
    MERGE {_table_ref(config["analysis_table"])} T
    USING (
      SELECT
        @analysis_date AS analysis_date,
        @ticker AS ticker,
        @signal AS signal,
        @classification AS classification,
        @final_score AS final_score,
        @valuation_score AS valuation_score,
        @quality_score AS quality_score,
        @momentum_score AS momentum_score,
        @risk_score AS risk_score,
        @sell_score AS sell_score,
        @sell_signal AS sell_signal,
        @suggested_sell_price AS suggested_sell_price,
        @ai_sell_thesis AS ai_sell_thesis,
        @ai_sell_reasons AS ai_sell_reasons,
        @ai_sell_price_view AS ai_sell_price_view,
        @ai_sell_decision_support AS ai_sell_decision_support,
        @ai_summary AS ai_summary,
        @ai_analysis AS ai_analysis,
        @ai_risks AS ai_risks,
        @ai_opportunity AS ai_opportunity,
        @ai_decision_support AS ai_decision_support,
        @external_sources_json AS external_sources_json,
        @external_context_summary AS external_context_summary,
        @data_discrepancies AS data_discrepancies,
        @confidence_score AS confidence_score,
        @confidence_reason AS confidence_reason,
        @model_name AS model_name,
        @prompt_version AS prompt_version,
        @input_hash AS input_hash,
        @raw_response_json AS raw_response_json,
        CURRENT_TIMESTAMP() AS created_at
    ) S
    ON T.analysis_date = S.analysis_date AND T.ticker = S.ticker
    WHEN MATCHED THEN UPDATE SET
      signal = S.signal,
      classification = S.classification,
      final_score = S.final_score,
      valuation_score = S.valuation_score,
      quality_score = S.quality_score,
      momentum_score = S.momentum_score,
      risk_score = S.risk_score,
      sell_score = S.sell_score,
      sell_signal = S.sell_signal,
      suggested_sell_price = S.suggested_sell_price,
      ai_sell_thesis = S.ai_sell_thesis,
      ai_sell_reasons = S.ai_sell_reasons,
      ai_sell_price_view = S.ai_sell_price_view,
      ai_sell_decision_support = S.ai_sell_decision_support,
      ai_summary = S.ai_summary,
      ai_analysis = S.ai_analysis,
      ai_risks = S.ai_risks,
      ai_opportunity = S.ai_opportunity,
      ai_decision_support = S.ai_decision_support,
      external_sources_json = S.external_sources_json,
      external_context_summary = S.external_context_summary,
      data_discrepancies = S.data_discrepancies,
      confidence_score = S.confidence_score,
      confidence_reason = S.confidence_reason,
      model_name = S.model_name,
      prompt_version = S.prompt_version,
      input_hash = S.input_hash,
      raw_response_json = S.raw_response_json,
      created_at = S.created_at
    WHEN NOT MATCHED THEN INSERT ROW
    """
    params = [
        bigquery.ScalarQueryParameter("analysis_date", "DATE", row["analysis_date"]),
        bigquery.ScalarQueryParameter("ticker", "STRING", row["ticker"]),
        bigquery.ScalarQueryParameter("signal", "STRING", row.get("signal")),
        bigquery.ScalarQueryParameter("classification", "STRING", row.get("classification")),
        bigquery.ScalarQueryParameter("final_score", "FLOAT64", row.get("final_score")),
        bigquery.ScalarQueryParameter("valuation_score", "FLOAT64", row.get("valuation_score")),
        bigquery.ScalarQueryParameter("quality_score", "FLOAT64", row.get("quality_score")),
        bigquery.ScalarQueryParameter("momentum_score", "FLOAT64", row.get("momentum_score")),
        bigquery.ScalarQueryParameter("risk_score", "FLOAT64", row.get("risk_score")),
        bigquery.ScalarQueryParameter("sell_score", "FLOAT64", row.get("sell_score")),
        bigquery.ScalarQueryParameter("sell_signal", "STRING", row.get("sell_signal")),
        bigquery.ScalarQueryParameter("suggested_sell_price", "FLOAT64", row.get("suggested_sell_price")),
        bigquery.ScalarQueryParameter("ai_sell_thesis", "STRING", row.get("ai_sell_thesis")),
        bigquery.ScalarQueryParameter("ai_sell_reasons", "STRING", row.get("ai_sell_reasons")),
        bigquery.ScalarQueryParameter("ai_sell_price_view", "STRING", row.get("ai_sell_price_view")),
        bigquery.ScalarQueryParameter("ai_sell_decision_support", "STRING", row.get("ai_sell_decision_support")),
        bigquery.ScalarQueryParameter("ai_summary", "STRING", row.get("ai_summary")),
        bigquery.ScalarQueryParameter("ai_analysis", "STRING", row.get("ai_analysis")),
        bigquery.ScalarQueryParameter("ai_risks", "STRING", row.get("ai_risks")),
        bigquery.ScalarQueryParameter("ai_opportunity", "STRING", row.get("ai_opportunity")),
        bigquery.ScalarQueryParameter("ai_decision_support", "STRING", row.get("ai_decision_support")),
        bigquery.ScalarQueryParameter("external_sources_json", "STRING", row.get("external_sources_json")),
        bigquery.ScalarQueryParameter("external_context_summary", "STRING", row.get("external_context_summary")),
        bigquery.ScalarQueryParameter("data_discrepancies", "STRING", row.get("data_discrepancies")),
        bigquery.ScalarQueryParameter("confidence_score", "FLOAT64", row.get("confidence_score")),
        bigquery.ScalarQueryParameter("confidence_reason", "STRING", row.get("confidence_reason")),
        bigquery.ScalarQueryParameter("model_name", "STRING", row.get("model_name")),
        bigquery.ScalarQueryParameter("prompt_version", "STRING", row.get("prompt_version")),
        bigquery.ScalarQueryParameter("input_hash", "STRING", row.get("input_hash")),
        bigquery.ScalarQueryParameter("raw_response_json", "STRING", row.get("raw_response_json")),
    ]
    client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).result()


def merge_summary(config, row):
    client = bigquery.Client(project=config["project_id"])
    sql = f"""
    MERGE {_table_ref(config["summary_table"])} T
    USING (
      SELECT
        @analysis_date AS analysis_date,
        @portfolio_summary AS portfolio_summary,
        @top_opportunities AS top_opportunities,
        @overvalued_summary AS overvalued_summary,
        @risk_summary AS risk_summary,
        @dashboard_summary AS dashboard_summary,
        @alert_title AS alert_title,
        @alert_body AS alert_body,
        @alert_sent AS alert_sent,
        @alert_error AS alert_error,
        @model_name AS model_name,
        @prompt_version AS prompt_version,
        CURRENT_TIMESTAMP() AS created_at
    ) S
    ON T.analysis_date = S.analysis_date
    WHEN MATCHED THEN UPDATE SET
      portfolio_summary = S.portfolio_summary,
      top_opportunities = S.top_opportunities,
      overvalued_summary = S.overvalued_summary,
      risk_summary = S.risk_summary,
      dashboard_summary = S.dashboard_summary,
      alert_title = S.alert_title,
      alert_body = S.alert_body,
      alert_sent = S.alert_sent,
      alert_error = S.alert_error,
      model_name = S.model_name,
      prompt_version = S.prompt_version,
      created_at = S.created_at
    WHEN NOT MATCHED THEN INSERT ROW
    """
    params = [
        bigquery.ScalarQueryParameter("analysis_date", "DATE", row["analysis_date"]),
        bigquery.ScalarQueryParameter("portfolio_summary", "STRING", row.get("portfolio_summary")),
        bigquery.ScalarQueryParameter("top_opportunities", "STRING", row.get("top_opportunities")),
        bigquery.ScalarQueryParameter("overvalued_summary", "STRING", row.get("overvalued_summary")),
        bigquery.ScalarQueryParameter("risk_summary", "STRING", row.get("risk_summary")),
        bigquery.ScalarQueryParameter("dashboard_summary", "STRING", row.get("dashboard_summary")),
        bigquery.ScalarQueryParameter("alert_title", "STRING", row.get("alert_title")),
        bigquery.ScalarQueryParameter("alert_body", "STRING", row.get("alert_body")),
        bigquery.ScalarQueryParameter("alert_sent", "BOOL", row.get("alert_sent")),
        bigquery.ScalarQueryParameter("alert_error", "STRING", row.get("alert_error")),
        bigquery.ScalarQueryParameter("model_name", "STRING", row.get("model_name")),
        bigquery.ScalarQueryParameter("prompt_version", "STRING", row.get("prompt_version")),
    ]
    client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).result()


def to_jsonable(value):
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return value


def row_to_json(row):
    return json.dumps({k: to_jsonable(v) for k, v in row.items()}, ensure_ascii=True, sort_keys=True)

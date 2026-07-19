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
      ai_technical_view STRING,
      ai_fair_value_view STRING,
      ai_data_quality_view STRING,
      ai_opportunity STRING,
      ai_decision_support STRING,
      ai_valuation_opinion STRING,
      ai_signal_agreement STRING,
      ai_final_alert_action STRING,
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
      summary_type STRING,
      portfolio_summary STRING,
      top_opportunities STRING,
      overvalued_summary STRING,
      risk_summary STRING,
      dashboard_summary STRING,
      alert_title STRING,
      alert_body STRING,
      discord_summary STRING,
      full_report STRING,
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
        ("ai_valuation_opinion", "STRING"),
        ("ai_signal_agreement", "STRING"),
        ("ai_final_alert_action", "STRING"),
        ("ai_technical_view", "STRING"),
        ("ai_fair_value_view", "STRING"),
        ("ai_data_quality_view", "STRING"),
    ]:
        client.query(
            f"ALTER TABLE {_table_ref(config['analysis_table'])} ADD COLUMN IF NOT EXISTS {column_name} {column_type}"
        ).result()

    client.query(
        f"ALTER TABLE {_table_ref(config['summary_table'])} ADD COLUMN IF NOT EXISTS summary_type STRING"
    ).result()
    client.query(
        f"ALTER TABLE {_table_ref(config['summary_table'])} ADD COLUMN IF NOT EXISTS discord_summary STRING"
    ).result()
    client.query(
        f"ALTER TABLE {_table_ref(config['summary_table'])} ADD COLUMN IF NOT EXISTS full_report STRING"
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


def _table_parts(table_id):
    project_id, dataset_id, table_name = table_id.split(".")
    return project_id, dataset_id, table_name


def _available_columns(client, table_id):
    project_id, dataset_id, table_name = _table_parts(table_id)
    sql = f"""
    SELECT column_name
    FROM `{project_id}.{dataset_id}.INFORMATION_SCHEMA.COLUMNS`
    WHERE table_name = @table_name
    """
    params = [bigquery.ScalarQueryParameter("table_name", "STRING", table_name)]
    rows = client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).result()
    return {row["column_name"] for row in rows}


def _select_expr(column_name, available, fallback_type="FLOAT64"):
    if column_name in available:
        return column_name
    return f"CAST(NULL AS {fallback_type}) AS {column_name}"


def fetch_daily_signals(config, analysis_date, tickers=None, analysis_scope="candidates", max_tickers=None):
    client = bigquery.Client(project=config["project_id"])
    available = _available_columns(client, config["signal_table"])
    params = [
        bigquery.ScalarQueryParameter("analysis_date", "DATE", analysis_date),
        bigquery.ScalarQueryParameter("prompt_version", "STRING", config["prompt_version"]),
        bigquery.ScalarQueryParameter("model_name", "STRING", config["openai_model"]),
    ]
    ticker_filter = ""
    if tickers:
        ticker_filter = "AND ticker IN UNNEST(@tickers)"
        params.append(bigquery.ArrayQueryParameter("tickers", "STRING", tickers))
    scope_filter = ""
    if analysis_scope == "candidates":
        scope_filter = """
        AND (
          signal IN ("COMPRAR_OBSERVAR", "VENDER_OBSERVAR")
          OR sell_signal = "VENTA_CLARA"
        )
        """
    elif analysis_scope == "remaining":
        scope_filter = f"""
        AND NOT EXISTS (
          SELECT 1
          FROM {_table_ref(config["analysis_table"])} a
          WHERE a.analysis_date = @analysis_date
            AND a.ticker = s.ticker
            AND a.prompt_version = @prompt_version
            AND a.model_name = @model_name
            AND a.ai_summary IS NOT NULL
            AND a.ai_summary != "ERROR_GENERANDO_ANALISIS"
        )
        """
    limit_clause = ""
    if max_tickers and analysis_scope == "candidates" and not tickers:
        limit_clause = "LIMIT @max_tickers"
        params.append(bigquery.ScalarQueryParameter("max_tickers", "INT64", int(max_tickers)))

    sql = f"""
    SELECT
      analysis_date,
      ticker,
      last_close,
      classification,
      financial_data_status,
      {_select_expr("asset_type", available, "STRING")},
      {_select_expr("sector", available, "STRING")},
      {_select_expr("industry", available, "STRING")},
      {_select_expr("peer_group", available, "STRING")},
      {_select_expr("valuation_model", available, "STRING")},
      {_select_expr("primary_metric", available, "STRING")},
      {_select_expr("peer_count", available, "INT64")},
      {_select_expr("peer_median_pe", available)},
      {_select_expr("peer_median_forward_pe", available)},
      {_select_expr("peer_median_price_to_book", available)},
      {_select_expr("peer_median_price_to_sales", available)},
      {_select_expr("peer_median_ev_to_ebitda", available)},
      {_select_expr("peer_median_roe", available)},
      {_select_expr("peer_median_profit_margin", available)},
      {_select_expr("pe_percentile", available)},
      {_select_expr("forward_pe_percentile", available)},
      {_select_expr("price_to_book_percentile", available)},
      {_select_expr("price_to_sales_percentile", available)},
      {_select_expr("ev_to_ebitda_percentile", available)},
      {_select_expr("roe_percentile", available)},
      {_select_expr("profit_margin_percentile", available)},
      {_select_expr("peer_relative_score", available)},
      {_select_expr("peer_valuation_label", available, "STRING")},
      {_select_expr("technical_score", available)},
      {_select_expr("data_quality_score", available)},
      {_select_expr("missing_data_impact", available, "STRING")},
      {_select_expr("risk_level", available, "STRING")},
      {_select_expr("technical_trend", available, "STRING")},
      {_select_expr("fair_value_estimate", available)},
      {_select_expr("conservative_fair_value", available)},
      {_select_expr("margin_of_safety_pct", available)},
      {_select_expr("suggested_buy_price", available)},
      {_select_expr("adaptive_forward_pe_limit", available)},
      {_select_expr("adaptive_pe_limit", available)},
      {_select_expr("adaptive_price_to_sales_limit", available)},
      {_select_expr("adaptive_ev_to_ebitda_limit", available)},
      {_select_expr("adaptive_price_to_book_limit", available)},
      {_select_expr("buy_multiple_guardrail_pass", available, "BOOL")},
      {_select_expr("buy_guardrail_reason", available, "STRING")},
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
      {_select_expr("return_120d", available)},
      {_select_expr("sma_20", available)},
      {_select_expr("sma_60", available)},
      {_select_expr("sma_120", available)},
      {_select_expr("high_252d", available)},
      {_select_expr("low_252d", available)},
      volatility_20d,
      volume_vs_20d_avg,
      pe_ratio,
      forward_pe,
      {_select_expr("price_to_book", available)},
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
    FROM {_table_ref(config["signal_table"])} s
    WHERE analysis_date = @analysis_date
    {ticker_filter}
    {scope_filter}
    ORDER BY
      CASE
        WHEN signal = "COMPRAR_OBSERVAR" THEN 1
        WHEN sell_signal = "VENTA_CLARA" OR signal = "VENDER_OBSERVAR" THEN 2
        ELSE 3
      END,
      GREATEST(COALESCE(final_score, 0), COALESCE(sell_score, 0)) DESC,
      ticker
    {limit_clause}
    """
    job_config = bigquery.QueryJobConfig(query_parameters=params)
    return [dict(row) for row in client.query(sql, job_config=job_config).result()]


def fetch_existing_successful_analyses(config, analysis_date, tickers=None):
    client = bigquery.Client(project=config["project_id"])
    params = [
        bigquery.ScalarQueryParameter("analysis_date", "DATE", analysis_date),
        bigquery.ScalarQueryParameter("prompt_version", "STRING", config["prompt_version"]),
        bigquery.ScalarQueryParameter("model_name", "STRING", config["openai_model"]),
    ]
    ticker_filter = ""
    if tickers:
        ticker_filter = "AND ticker IN UNNEST(@tickers)"
        params.append(bigquery.ArrayQueryParameter("tickers", "STRING", tickers))

    sql = f"""
    SELECT *
    FROM {_table_ref(config["analysis_table"])}
    WHERE analysis_date = @analysis_date
      AND prompt_version = @prompt_version
      AND model_name = @model_name
      AND ai_summary IS NOT NULL
      AND ai_summary != "ERROR_GENERANDO_ANALISIS"
      {ticker_filter}
    """
    job_config = bigquery.QueryJobConfig(query_parameters=params)
    return {row["ticker"]: dict(row) for row in client.query(sql, job_config=job_config).result()}


def fetch_summary_state(config, analysis_date, summary_type="daily"):
    client = bigquery.Client(project=config["project_id"])
    sql = f"""
    SELECT alert_sent, alert_error
    FROM {_table_ref(config["summary_table"])}
    WHERE analysis_date = @analysis_date
      AND COALESCE(summary_type, "daily") = @summary_type
      AND prompt_version = @prompt_version
    ORDER BY created_at DESC
    LIMIT 1
    """
    params = [
        bigquery.ScalarQueryParameter("analysis_date", "DATE", analysis_date),
        bigquery.ScalarQueryParameter("summary_type", "STRING", summary_type),
        bigquery.ScalarQueryParameter("prompt_version", "STRING", config["prompt_version"]),
    ]
    rows = list(client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).result())
    return dict(rows[0]) if rows else None


def fetch_weekly_changes(config, analysis_date):
    client = bigquery.Client(project=config["project_id"])
    status_changes_table = config.get("status_changes_table")
    if status_changes_table:
        try:
            sql = f"""
            SELECT *
            FROM {_table_ref(status_changes_table)}
            WHERE analysis_date BETWEEN DATE_SUB(@analysis_date, INTERVAL 7 DAY) AND @analysis_date
            ORDER BY analysis_date DESC, ticker
            LIMIT 200
            """
            params = [bigquery.ScalarQueryParameter("analysis_date", "DATE", analysis_date)]
            return [dict(row) for row in client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).result()]
        except Exception:
            pass

    available = _available_columns(client, config["signal_table"])
    sql = f"""
    WITH week_rows AS (
      SELECT
        analysis_date,
        ticker,
        signal,
        sell_signal,
        classification,
        last_close,
        final_score,
        sell_score,
        {_select_expr("risk_level", available, "STRING")},
        {_select_expr("technical_trend", available, "STRING")},
        {_select_expr("margin_of_safety_pct", available)},
        {_select_expr("conservative_fair_value", available)},
        return_5d,
        return_20d,
        return_60d,
        LAG(signal) OVER (PARTITION BY ticker ORDER BY analysis_date) AS previous_signal,
        LAG(sell_signal) OVER (PARTITION BY ticker ORDER BY analysis_date) AS previous_sell_signal,
        LAG(classification) OVER (PARTITION BY ticker ORDER BY analysis_date) AS previous_classification,
        LAG(final_score) OVER (PARTITION BY ticker ORDER BY analysis_date) AS previous_final_score,
        LAG(last_close) OVER (PARTITION BY ticker ORDER BY analysis_date) AS previous_close,
        LAG({_select_expr("risk_level", available, "STRING").replace(' AS risk_level', '')}) OVER (PARTITION BY ticker ORDER BY analysis_date) AS previous_risk_level,
        LAG({_select_expr("technical_trend", available, "STRING").replace(' AS technical_trend', '')}) OVER (PARTITION BY ticker ORDER BY analysis_date) AS previous_technical_trend
      FROM {_table_ref(config["signal_table"])}
      WHERE analysis_date BETWEEN DATE_SUB(@analysis_date, INTERVAL 7 DAY) AND @analysis_date
    ),
    latest AS (
      SELECT *
      FROM week_rows
      WHERE analysis_date = @analysis_date
    )
    SELECT
      *,
      ROUND(SAFE_DIVIDE(last_close - previous_close, previous_close), 4) AS weekly_price_change,
      ROUND(final_score - previous_final_score, 2) AS weekly_score_change,
      CASE
        WHEN signal != previous_signal OR sell_signal != previous_sell_signal OR classification != previous_classification THEN TRUE
        ELSE FALSE
      END AS state_changed,
      CASE
        WHEN risk_level != previous_risk_level THEN TRUE
        ELSE FALSE
      END AS risk_changed,
      CASE
        WHEN technical_trend != previous_technical_trend THEN TRUE
        ELSE FALSE
      END AS trend_changed
    FROM latest
    ORDER BY
      state_changed DESC,
      ABS(COALESCE(weekly_price_change, 0)) DESC,
      ABS(COALESCE(weekly_score_change, 0)) DESC,
      ticker
    """
    params = [bigquery.ScalarQueryParameter("analysis_date", "DATE", analysis_date)]
    return [dict(row) for row in client.query(sql, job_config=bigquery.QueryJobConfig(query_parameters=params)).result()]


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
        @ai_technical_view AS ai_technical_view,
        @ai_fair_value_view AS ai_fair_value_view,
        @ai_data_quality_view AS ai_data_quality_view,
        @ai_opportunity AS ai_opportunity,
        @ai_decision_support AS ai_decision_support,
        @ai_valuation_opinion AS ai_valuation_opinion,
        @ai_signal_agreement AS ai_signal_agreement,
        @ai_final_alert_action AS ai_final_alert_action,
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
      ai_technical_view = S.ai_technical_view,
      ai_fair_value_view = S.ai_fair_value_view,
      ai_data_quality_view = S.ai_data_quality_view,
      ai_opportunity = S.ai_opportunity,
      ai_decision_support = S.ai_decision_support,
      ai_valuation_opinion = S.ai_valuation_opinion,
      ai_signal_agreement = S.ai_signal_agreement,
      ai_final_alert_action = S.ai_final_alert_action,
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
    WHEN NOT MATCHED THEN INSERT (
      analysis_date,
      ticker,
      signal,
      classification,
      final_score,
      valuation_score,
      quality_score,
      momentum_score,
      risk_score,
      ai_summary,
      ai_analysis,
      ai_risks,
      ai_technical_view,
      ai_fair_value_view,
      ai_data_quality_view,
      ai_opportunity,
      ai_decision_support,
      ai_valuation_opinion,
      ai_signal_agreement,
      ai_final_alert_action,
      external_sources_json,
      external_context_summary,
      data_discrepancies,
      confidence_score,
      confidence_reason,
      model_name,
      prompt_version,
      input_hash,
      raw_response_json,
      created_at,
      sell_score,
      sell_signal,
      suggested_sell_price,
      ai_sell_thesis,
      ai_sell_reasons,
      ai_sell_price_view,
      ai_sell_decision_support
    ) VALUES (
      S.analysis_date,
      S.ticker,
      S.signal,
      S.classification,
      S.final_score,
      S.valuation_score,
      S.quality_score,
      S.momentum_score,
      S.risk_score,
      S.ai_summary,
      S.ai_analysis,
      S.ai_risks,
      S.ai_technical_view,
      S.ai_fair_value_view,
      S.ai_data_quality_view,
      S.ai_opportunity,
      S.ai_decision_support,
      S.ai_valuation_opinion,
      S.ai_signal_agreement,
      S.ai_final_alert_action,
      S.external_sources_json,
      S.external_context_summary,
      S.data_discrepancies,
      S.confidence_score,
      S.confidence_reason,
      S.model_name,
      S.prompt_version,
      S.input_hash,
      S.raw_response_json,
      S.created_at,
      S.sell_score,
      S.sell_signal,
      S.suggested_sell_price,
      S.ai_sell_thesis,
      S.ai_sell_reasons,
      S.ai_sell_price_view,
      S.ai_sell_decision_support
    )
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
        bigquery.ScalarQueryParameter("ai_technical_view", "STRING", row.get("ai_technical_view")),
        bigquery.ScalarQueryParameter("ai_fair_value_view", "STRING", row.get("ai_fair_value_view")),
        bigquery.ScalarQueryParameter("ai_data_quality_view", "STRING", row.get("ai_data_quality_view")),
        bigquery.ScalarQueryParameter("ai_opportunity", "STRING", row.get("ai_opportunity")),
        bigquery.ScalarQueryParameter("ai_decision_support", "STRING", row.get("ai_decision_support")),
        bigquery.ScalarQueryParameter("ai_valuation_opinion", "STRING", row.get("ai_valuation_opinion")),
        bigquery.ScalarQueryParameter("ai_signal_agreement", "STRING", row.get("ai_signal_agreement")),
        bigquery.ScalarQueryParameter("ai_final_alert_action", "STRING", row.get("ai_final_alert_action")),
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
        @summary_type AS summary_type,
        @portfolio_summary AS portfolio_summary,
        @top_opportunities AS top_opportunities,
        @overvalued_summary AS overvalued_summary,
        @risk_summary AS risk_summary,
        @dashboard_summary AS dashboard_summary,
        @alert_title AS alert_title,
        @alert_body AS alert_body,
        @discord_summary AS discord_summary,
        @full_report AS full_report,
        @alert_sent AS alert_sent,
        @alert_error AS alert_error,
        @model_name AS model_name,
        @prompt_version AS prompt_version,
        CURRENT_TIMESTAMP() AS created_at
    ) S
    ON T.analysis_date = S.analysis_date AND COALESCE(T.summary_type, "daily") = S.summary_type
    WHEN MATCHED THEN UPDATE SET
      summary_type = S.summary_type,
      portfolio_summary = S.portfolio_summary,
      top_opportunities = S.top_opportunities,
      overvalued_summary = S.overvalued_summary,
      risk_summary = S.risk_summary,
      dashboard_summary = S.dashboard_summary,
      alert_title = S.alert_title,
      alert_body = S.alert_body,
      discord_summary = S.discord_summary,
      full_report = S.full_report,
      alert_sent = S.alert_sent,
      alert_error = S.alert_error,
      model_name = S.model_name,
      prompt_version = S.prompt_version,
      created_at = S.created_at
    WHEN NOT MATCHED THEN INSERT (
      analysis_date,
      summary_type,
      portfolio_summary,
      top_opportunities,
      overvalued_summary,
      risk_summary,
      dashboard_summary,
      alert_title,
      alert_body,
      discord_summary,
      full_report,
      alert_sent,
      alert_error,
      model_name,
      prompt_version,
      created_at
    ) VALUES (
      S.analysis_date,
      S.summary_type,
      S.portfolio_summary,
      S.top_opportunities,
      S.overvalued_summary,
      S.risk_summary,
      S.dashboard_summary,
      S.alert_title,
      S.alert_body,
      S.discord_summary,
      S.full_report,
      S.alert_sent,
      S.alert_error,
      S.model_name,
      S.prompt_version,
      S.created_at
    )
    """
    params = [
        bigquery.ScalarQueryParameter("analysis_date", "DATE", row["analysis_date"]),
        bigquery.ScalarQueryParameter("summary_type", "STRING", row.get("summary_type", "daily")),
        bigquery.ScalarQueryParameter("portfolio_summary", "STRING", row.get("portfolio_summary")),
        bigquery.ScalarQueryParameter("top_opportunities", "STRING", row.get("top_opportunities")),
        bigquery.ScalarQueryParameter("overvalued_summary", "STRING", row.get("overvalued_summary")),
        bigquery.ScalarQueryParameter("risk_summary", "STRING", row.get("risk_summary")),
        bigquery.ScalarQueryParameter("dashboard_summary", "STRING", row.get("dashboard_summary")),
        bigquery.ScalarQueryParameter("alert_title", "STRING", row.get("alert_title")),
        bigquery.ScalarQueryParameter("alert_body", "STRING", row.get("alert_body")),
        bigquery.ScalarQueryParameter("discord_summary", "STRING", row.get("discord_summary")),
        bigquery.ScalarQueryParameter("full_report", "STRING", row.get("full_report")),
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

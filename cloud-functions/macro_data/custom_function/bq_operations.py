import uuid

from google.cloud import bigquery


MARKET_SCHEMA = [
    bigquery.SchemaField("snapshot_slot", "TIMESTAMP"),
    bigquery.SchemaField("snapshot_date", "DATE"),
    bigquery.SchemaField("signal_hour", "STRING"),
    bigquery.SchemaField("symbol", "STRING"),
    bigquery.SchemaField("factor_name", "STRING"),
    bigquery.SchemaField("close", "FLOAT"),
    bigquery.SchemaField("previous_close", "FLOAT"),
    bigquery.SchemaField("return_1d", "FLOAT"),
    bigquery.SchemaField("return_5d", "FLOAT"),
    bigquery.SchemaField("return_20d", "FLOAT"),
    bigquery.SchemaField("source", "STRING"),
    bigquery.SchemaField("loaded_at", "TIMESTAMP"),
]

NEWS_SCHEMA = [
    bigquery.SchemaField("snapshot_slot", "TIMESTAMP"),
    bigquery.SchemaField("snapshot_date", "DATE"),
    bigquery.SchemaField("signal_hour", "STRING"),
    bigquery.SchemaField("topic", "STRING"),
    bigquery.SchemaField("query", "STRING"),
    bigquery.SchemaField("article_count", "INTEGER"),
    bigquery.SchemaField("top_source_countries", "STRING"),
    bigquery.SchemaField("sample_titles", "STRING"),
    bigquery.SchemaField("source", "STRING"),
    bigquery.SchemaField("loaded_at", "TIMESTAMP"),
]

EARNINGS_SCHEMA = [
    bigquery.SchemaField("snapshot_slot", "TIMESTAMP"),
    bigquery.SchemaField("snapshot_date", "DATE"),
    bigquery.SchemaField("signal_hour", "STRING"),
    bigquery.SchemaField("ticker", "STRING"),
    bigquery.SchemaField("earnings_date", "DATE"),
    bigquery.SchemaField("days_to_earnings", "INTEGER"),
    bigquery.SchemaField("earnings_time", "STRING"),
    bigquery.SchemaField("eps_estimate", "FLOAT"),
    bigquery.SchemaField("reported_eps", "FLOAT"),
    bigquery.SchemaField("surprise_pct", "FLOAT"),
    bigquery.SchemaField("event_status", "STRING"),
    bigquery.SchemaField("source", "STRING"),
    bigquery.SchemaField("loaded_at", "TIMESTAMP"),
]


def _table_ref(table):
    return f"`{table}`"


def fetch_portfolio_tickers(config):
    client = bigquery.Client(project=config["project_id"])
    query = f"""
    SELECT DISTINCT UPPER(ticker) AS ticker
    FROM {_table_ref(config["portfolio_table"])}
    WHERE enabled = TRUE
      AND ticker IS NOT NULL
    ORDER BY ticker
    """
    try:
        rows = list(client.query(query).result())
    except Exception:
        return []
    return [row["ticker"] for row in rows if row["ticker"]]


def ensure_tables(config):
    client = bigquery.Client(project=config["project_id"])
    market_table = bigquery.Table(config["market_table"], schema=MARKET_SCHEMA)
    market_table.time_partitioning = bigquery.TimePartitioning(field="snapshot_date")
    market_table.clustering_fields = ["factor_name", "symbol"]
    client.create_table(market_table, exists_ok=True)

    news_table = bigquery.Table(config["news_table"], schema=NEWS_SCHEMA)
    news_table.time_partitioning = bigquery.TimePartitioning(field="snapshot_date")
    news_table.clustering_fields = ["topic"]
    client.create_table(news_table, exists_ok=True)

    earnings_table = bigquery.Table(config["earnings_table"], schema=EARNINGS_SCHEMA)
    earnings_table.time_partitioning = bigquery.TimePartitioning(field="snapshot_date")
    earnings_table.clustering_fields = ["ticker", "event_status"]
    client.create_table(earnings_table, exists_ok=True)


def merge_market_rows(config, rows):
    if not rows:
        return 0
    client = bigquery.Client(project=config["project_id"])
    job_config = bigquery.LoadJobConfig(
        schema=MARKET_SCHEMA,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    temp_table = f"{config['market_table']}_temp_{uuid.uuid4().hex}"
    client.load_table_from_json(rows, temp_table, job_config=job_config).result()
    try:
        query = f"""
        MERGE {_table_ref(config["market_table"])} T
        USING {_table_ref(temp_table)} S
        ON T.snapshot_slot = S.snapshot_slot
       AND T.symbol = S.symbol
        WHEN MATCHED THEN UPDATE SET
          snapshot_date = S.snapshot_date,
          signal_hour = S.signal_hour,
          factor_name = S.factor_name,
          close = S.close,
          previous_close = S.previous_close,
          return_1d = S.return_1d,
          return_5d = S.return_5d,
          return_20d = S.return_20d,
          source = S.source,
          loaded_at = S.loaded_at
        WHEN NOT MATCHED THEN INSERT (
          snapshot_slot, snapshot_date, signal_hour, symbol, factor_name, close, previous_close,
          return_1d, return_5d, return_20d, source, loaded_at
        ) VALUES (
          S.snapshot_slot, S.snapshot_date, S.signal_hour, S.symbol, S.factor_name, S.close, S.previous_close,
          S.return_1d, S.return_5d, S.return_20d, S.source, S.loaded_at
        )
        """
        client.query(query).result()
    finally:
        client.delete_table(temp_table, not_found_ok=True)
    return len(rows)


def merge_news_rows(config, rows):
    if not rows:
        return 0
    client = bigquery.Client(project=config["project_id"])
    job_config = bigquery.LoadJobConfig(
        schema=NEWS_SCHEMA,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    temp_table = f"{config['news_table']}_temp_{uuid.uuid4().hex}"
    client.load_table_from_json(rows, temp_table, job_config=job_config).result()
    try:
        query = f"""
        MERGE {_table_ref(config["news_table"])} T
        USING {_table_ref(temp_table)} S
        ON T.snapshot_slot = S.snapshot_slot
       AND T.topic = S.topic
        WHEN MATCHED THEN UPDATE SET
          snapshot_date = S.snapshot_date,
          signal_hour = S.signal_hour,
          query = S.query,
          article_count = S.article_count,
          top_source_countries = S.top_source_countries,
          sample_titles = S.sample_titles,
          source = S.source,
          loaded_at = S.loaded_at
        WHEN NOT MATCHED THEN INSERT (
          snapshot_slot, snapshot_date, signal_hour, topic, query, article_count,
          top_source_countries, sample_titles, source, loaded_at
        ) VALUES (
          S.snapshot_slot, S.snapshot_date, S.signal_hour, S.topic, S.query, S.article_count,
          S.top_source_countries, S.sample_titles, S.source, S.loaded_at
        )
        """
        client.query(query).result()
    finally:
        client.delete_table(temp_table, not_found_ok=True)
    return len(rows)


def merge_earnings_rows(config, rows):
    if not rows:
        return 0
    client = bigquery.Client(project=config["project_id"])
    job_config = bigquery.LoadJobConfig(
        schema=EARNINGS_SCHEMA,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    temp_table = f"{config['earnings_table']}_temp_{uuid.uuid4().hex}"
    client.load_table_from_json(rows, temp_table, job_config=job_config).result()
    try:
        query = f"""
        MERGE {_table_ref(config["earnings_table"])} T
        USING {_table_ref(temp_table)} S
        ON T.snapshot_slot = S.snapshot_slot
       AND T.ticker = S.ticker
        WHEN MATCHED THEN UPDATE SET
          snapshot_date = S.snapshot_date,
          signal_hour = S.signal_hour,
          earnings_date = S.earnings_date,
          days_to_earnings = S.days_to_earnings,
          earnings_time = S.earnings_time,
          eps_estimate = S.eps_estimate,
          reported_eps = S.reported_eps,
          surprise_pct = S.surprise_pct,
          event_status = S.event_status,
          source = S.source,
          loaded_at = S.loaded_at
        WHEN NOT MATCHED THEN INSERT (
          snapshot_slot, snapshot_date, signal_hour, ticker, earnings_date, days_to_earnings,
          earnings_time, eps_estimate, reported_eps, surprise_pct, event_status, source, loaded_at
        ) VALUES (
          S.snapshot_slot, S.snapshot_date, S.signal_hour, S.ticker, S.earnings_date, S.days_to_earnings,
          S.earnings_time, S.eps_estimate, S.reported_eps, S.surprise_pct, S.event_status, S.source, S.loaded_at
        )
        """
        client.query(query).result()
    finally:
        client.delete_table(temp_table, not_found_ok=True)
    return len(rows)

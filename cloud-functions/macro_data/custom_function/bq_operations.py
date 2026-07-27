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


def _table_ref(table):
    return f"`{table}`"


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

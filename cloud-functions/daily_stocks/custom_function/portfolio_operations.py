from google.cloud import bigquery


def fetch_enabled_tickers(project_id, portfolio_table):
    client = bigquery.Client(project=project_id)
    query = f"""
    SELECT ticker
    FROM `{portfolio_table}`
    WHERE enabled = TRUE
    ORDER BY ticker
    """
    return [row["ticker"] for row in client.query(query).result()]


def fetch_enabled_assets(project_id, portfolio_table):
    client = bigquery.Client(project=project_id)
    query = f"""
    SELECT
      ticker,
      UPPER(COALESCE(asset_type, "STOCK")) AS asset_type
    FROM `{portfolio_table}`
    WHERE enabled = TRUE
    ORDER BY ticker
    """
    return [{"ticker": row["ticker"], "asset_type": row["asset_type"]} for row in client.query(query).result()]


def fetch_asset_types(project_id, portfolio_table, tickers):
    if not tickers:
        return {}

    client = bigquery.Client(project=project_id)
    query = f"""
    SELECT
      ticker,
      UPPER(COALESCE(asset_type, "STOCK")) AS asset_type
    FROM `{portfolio_table}`
    WHERE ticker IN UNNEST(@tickers)
    """
    job_config = bigquery.QueryJobConfig(
        query_parameters=[bigquery.ArrayQueryParameter("tickers", "STRING", tickers)]
    )
    return {row["ticker"]: row["asset_type"] for row in client.query(query, job_config=job_config).result()}

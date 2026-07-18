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

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


def fetch_enabled_tickers_with_peers(project_id, portfolio_table, peer_universe_table):
    client = bigquery.Client(project=project_id)
    query = f"""
    WITH portfolio AS (
      SELECT ticker
      FROM `{portfolio_table}`
      WHERE enabled = TRUE
    ),
    peers AS (
      SELECT peer_ticker AS ticker
      FROM `{peer_universe_table}`
      WHERE ticker IN (SELECT ticker FROM portfolio)
    )
    SELECT DISTINCT ticker
    FROM (
      SELECT ticker FROM portfolio
      UNION ALL
      SELECT ticker FROM peers
    )
    ORDER BY ticker
    """
    try:
        return [row["ticker"] for row in client.query(query).result()]
    except Exception:
        return fetch_enabled_tickers(project_id, portfolio_table)

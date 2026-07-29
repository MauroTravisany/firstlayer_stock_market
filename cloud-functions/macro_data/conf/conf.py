import os

from google.cloud import secretmanager


def access_secret_version(secret_id, version_id="latest", required=True):
    project_id = os.environ.get("PROJECT_ID")
    if not project_id:
        raise RuntimeError("PROJECT_ID environment variable is required")

    env_value = os.environ.get(secret_id)
    if env_value:
        return env_value.strip()

    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_id}/versions/{version_id}"
    try:
        response = client.access_secret_version(name=name)
        return response.payload.data.decode("UTF-8").strip()
    except Exception:
        if required:
            raise
        return None


def load_config():
    project_id = access_secret_version("project_id")
    dataset_id = access_secret_version("dataset_id")

    return {
        "project_id": project_id,
        "dataset_id": dataset_id,
        "market_table": f"{project_id}.{dataset_id}.{os.environ.get('MACRO_MARKET_TABLE_ID', 'macro_market_snapshot')}",
        "news_table": f"{project_id}.{dataset_id}.{os.environ.get('MACRO_NEWS_TABLE_ID', 'macro_news_signal')}",
        "earnings_table": f"{project_id}.{dataset_id}.{os.environ.get('MACRO_EARNINGS_TABLE_ID', 'macro_earnings_calendar')}",
        "portfolio_table": f"{project_id}.{dataset_id}.{os.environ.get('PORTFOLIO_TABLE_ID', 'portfolio_assets')}",
        "time_zone": os.environ.get("TIME_ZONE", "America/Santiago"),
        "gdelt_timespan": os.environ.get("GDELT_TIMESPAN", "4H"),
        "gdelt_maxrecords": int(os.environ.get("GDELT_MAX_RECORDS", "75")),
        "tickers": [
            ticker.strip().upper()
            for ticker in os.environ.get(
                "TICKERS",
                "AAPL,MSFT,NVDA,META,GOOG,GOOGL,AMZN,TSLA,MELI,COIN,BTC-USD,ETH-USD",
            ).replace(";", ",").split(",")
            if ticker.strip()
        ],
    }

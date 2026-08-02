import os

from google.cloud import secretmanager


def _env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "y", "si"}


def _env_int(name, default):
    value = os.environ.get(name)
    if value in (None, ""):
        return default
    return int(value)


def _env_float(name, default):
    value = os.environ.get(name)
    if value in (None, ""):
        return default
    return float(value)


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
    alpaca_base_url = (
        os.environ.get("ALPACA_BASE_URL")
        or access_secret_version(os.environ.get("ALPACA_BASE_URL_SECRET", "ALPACA_BASE_URL"), required=False)
        or "https://paper-api.alpaca.markets"
    ).rstrip("/")

    if "paper-api.alpaca.markets" not in alpaca_base_url:
        raise RuntimeError("Safety guard: only Alpaca Paper API is allowed in this service")

    return {
        "project_id": project_id,
        "dataset_id": dataset_id,
        "signals_table": f"{project_id}.{dataset_id}.{os.environ.get('TRADING_SIGNALS_TABLE_ID', 'trading_paper_signals_active')}",
        "results_table": f"{project_id}.{dataset_id}.{os.environ.get('TRADING_RESULTS_TABLE_ID', 'trading_paper_trade_results_active')}",
        "executions_table": f"{project_id}.{dataset_id}.{os.environ.get('ALPACA_EXECUTIONS_TABLE_ID', 'trading_alpaca_paper_executions')}",
        "alpaca_base_url": alpaca_base_url,
        "alpaca_api_key": access_secret_version(os.environ.get("ALPACA_API_KEY_SECRET", "ALPACA_API_KEY")),
        "alpaca_secret_key": access_secret_version(os.environ.get("ALPACA_SECRET_KEY_SECRET", "ALPACA_SECRET_KEY")),
        "execution_mode": os.environ.get("PAPER_EXECUTION_MODE", "paper").lower(),
        "equity_order_class": os.environ.get("ALPACA_EQUITY_ORDER_CLASS", "simple").lower(),
        "enable_crypto_orders": _env_bool("ALPACA_ENABLE_CRYPTO_ORDERS", True),
        "max_orders_per_run": _env_int("ALPACA_MAX_ORDERS_PER_RUN", 3),
        "max_orders_per_day": _env_int("ALPACA_MAX_ORDERS_PER_DAY", 5),
        "max_open_positions": _env_int("ALPACA_MAX_OPEN_POSITIONS", 5),
        "max_notional_usd": _env_float("ALPACA_MAX_NOTIONAL_USD", 10.0),
        "min_setup_score": _env_float("ALPACA_MIN_SETUP_SCORE", 0.0),
        "request_timeout_seconds": _env_float("ALPACA_REQUEST_TIMEOUT_SECONDS", 20.0),
    }

import os

from google.cloud import secretmanager


def _env_int(name, default):
    value = os.environ.get(name)
    return default if value in (None, "") else int(value)


def access_secret_version(secret_id, required=True):
    project_id = os.environ.get("PROJECT_ID")
    if not project_id:
        raise RuntimeError("PROJECT_ID environment variable is required")
    if os.environ.get(secret_id):
        return os.environ[secret_id].strip()
    name = f"projects/{project_id}/secrets/{secret_id}/versions/latest"
    try:
        return secretmanager.SecretManagerServiceClient().access_secret_version(name=name).payload.data.decode("UTF-8").strip()
    except Exception:
        if required:
            raise
        return None


def load_config():
    project_id = access_secret_version("project_id")
    dataset_id = access_secret_version("dataset_id")
    base_url = (os.environ.get("ALPACA_BASE_URL") or access_secret_version(os.environ.get("ALPACA_BASE_URL_SECRET", "ALPACA_BASE_URL"), required=False) or "https://paper-api.alpaca.markets").rstrip("/")
    if "paper-api.alpaca.markets" not in base_url:
        raise RuntimeError("Safety guard: only Alpaca Paper API is allowed")
    return {
        "project_id": project_id,
        "executions_table": f"{project_id}.{dataset_id}.{os.environ.get('ALPACA_EXECUTIONS_TABLE_ID', 'trading_alpaca_paper_executions')}",
        "positions_table": f"{project_id}.{dataset_id}.{os.environ.get('ALPACA_POSITIONS_TABLE_ID', 'trading_alpaca_paper_positions')}",
        "prices_table": f"{project_id}.{dataset_id}.{os.environ.get('STOCK_PRICES_TABLE_ID', 'valores_acciones_recientes')}",
        "alpaca_base_url": base_url,
        "alpaca_api_key": access_secret_version(os.environ.get("ALPACA_API_KEY_SECRET", "ALPACA_API_KEY")),
        "alpaca_secret_key": access_secret_version(os.environ.get("ALPACA_SECRET_KEY_SECRET", "ALPACA_SECRET_KEY")),
        "execution_mode": os.environ.get("PAPER_EXECUTION_MODE", "paper").lower(),
        "request_timeout_seconds": _env_int("ALPACA_REQUEST_TIMEOUT_SECONDS", 20),
        "max_exits_per_run": _env_int("ALPACA_MAX_EXITS_PER_RUN", 3),
    }

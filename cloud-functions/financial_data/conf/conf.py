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
    bucket_name = access_secret_version("bucket_name")
    project_id = access_secret_version("project_id")
    dataset_id = access_secret_version("dataset_id")
    statements_table_id = os.environ.get("FINANCIAL_STATEMENTS_TABLE_ID", "financial_statements")
    ratios_table_id = os.environ.get("FINANCIAL_RATIOS_TABLE_ID", "financial_ratios_snapshot")
    portfolio_table_id = os.environ.get("PORTFOLIO_TABLE_ID", "portfolio_assets")
    peer_universe_table_id = os.environ.get("PEER_UNIVERSE_TABLE_ID", "peer_universe")

    return {
        "bucket_name": bucket_name,
        "project_id": project_id,
        "dataset_id": dataset_id,
        "portfolio_table": f"{project_id}.{dataset_id}.{portfolio_table_id}",
        "peer_universe_table": f"{project_id}.{dataset_id}.{peer_universe_table_id}",
        "financial_statements_table": f"{project_id}.{dataset_id}.{statements_table_id}",
        "financial_ratios_table": f"{project_id}.{dataset_id}.{ratios_table_id}",
        "quality_table": f"{project_id}.{dataset_id}.{os.environ.get('DATA_QUALITY_TABLE_ID', 'pipeline_data_quality_daily')}",
        "alert_webhook_url": os.environ.get("ALERT_WEBHOOK_URL")
        or access_secret_version(os.environ.get("ALERT_WEBHOOK_URL_SECRET", "ALERT_WEBHOOK_URL"), required=False),
        "alert_webhook_type": os.environ.get("ALERT_WEBHOOK_TYPE", "auto").lower(),
    }

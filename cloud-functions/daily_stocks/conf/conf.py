import os

from google.cloud import secretmanager


def access_secret_version(secret_id, version_id="latest"):
    project_id = os.environ.get("PROJECT_ID")
    if not project_id:
        raise RuntimeError("PROJECT_ID environment variable is required")

    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{project_id}/secrets/{secret_id}/versions/{version_id}"
    response = client.access_secret_version(name=name)
    return response.payload.data.decode("UTF-8").strip()


def load_config():
    bucket_name = access_secret_version("bucket_name")
    project_id = access_secret_version("project_id")
    dataset_id = access_secret_version("dataset_id")
    table_id = access_secret_version("table_id")
    bq_table = f"{project_id}.{dataset_id}.{table_id}"
    portfolio_table_id = os.environ.get("PORTFOLIO_TABLE_ID", "portfolio_assets")
    portfolio_table = f"{project_id}.{dataset_id}.{portfolio_table_id}"

    return {
        "bucket_name": bucket_name,
        "bq_table": bq_table,
        "project_id": project_id,
        "dataset_id": dataset_id,
        "portfolio_table": portfolio_table,
    }

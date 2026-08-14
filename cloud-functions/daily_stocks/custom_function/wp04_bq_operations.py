"""Append-only BigQuery loaders for WP-04 shadow tables."""

from __future__ import annotations

import datetime as dt
import re
import uuid
from typing import Iterable

from google.cloud import bigquery

from .wp04_ingestion import validate_shadow_table

TABLE_ID = re.compile(
    r"^[A-Za-z][A-Za-z0-9-]{4,62}\.[A-Za-z0-9_]+\.[A-Za-z0-9_]+$"
)

PRICE_SCHEMA = (
    bigquery.SchemaField("raw_revision_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("raw_record_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("ingestion_run_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("provider", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("provider_symbol", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("ticker", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("asset_type", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("exchange", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("source_interval", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("source_timezone", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("bar_start", "TIMESTAMP", mode="REQUIRED"),
    bigquery.SchemaField("bar_end", "TIMESTAMP", mode="REQUIRED"),
    bigquery.SchemaField("open", "FLOAT64"),
    bigquery.SchemaField("high", "FLOAT64"),
    bigquery.SchemaField("low", "FLOAT64"),
    bigquery.SchemaField("close", "FLOAT64"),
    bigquery.SchemaField("adjusted_close", "FLOAT64"),
    bigquery.SchemaField("volume", "FLOAT64"),
    bigquery.SchemaField("currency", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("source_record_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("source_version", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("payload_hash", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("available_at", "TIMESTAMP", mode="REQUIRED"),
    bigquery.SchemaField("ingested_at", "TIMESTAMP", mode="REQUIRED"),
    bigquery.SchemaField("quality_status", "STRING", mode="REQUIRED"),
)

ACTION_SCHEMA = (
    bigquery.SchemaField("action_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("ingestion_run_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("ticker", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("action_type", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("ex_date", "DATE", mode="REQUIRED"),
    bigquery.SchemaField("record_date", "DATE"),
    bigquery.SchemaField("pay_date", "DATE"),
    bigquery.SchemaField("ratio", "FLOAT64"),
    bigquery.SchemaField("cash_amount", "FLOAT64"),
    bigquery.SchemaField("currency", "STRING"),
    bigquery.SchemaField("provider", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("source_record_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("source_version", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("source_published_at", "TIMESTAMP"),
    bigquery.SchemaField("available_at", "TIMESTAMP", mode="REQUIRED"),
    bigquery.SchemaField("ingested_at", "TIMESTAMP", mode="REQUIRED"),
    bigquery.SchemaField("revision", "INT64", mode="REQUIRED"),
    bigquery.SchemaField("backtest_eligible", "BOOL", mode="REQUIRED"),
    bigquery.SchemaField("quality_status", "STRING", mode="REQUIRED"),
)


def _schema_shape(schema: Iterable[bigquery.SchemaField]):
    return [
        (field.name, field.field_type, field.mode)
        for field in schema
    ]


def _validated_table_id(table_id: str, environment: str) -> str:
    table_id = validate_shadow_table(table_id, environment)
    if not TABLE_ID.fullmatch(table_id):
        raise ValueError("invalid BigQuery table identifier")
    return table_id


def _merge_query(
    destination: str,
    staging: str,
    key_field: str,
    columns: Iterable[str],
) -> str:
    columns = tuple(columns)
    if key_field not in columns:
        raise ValueError("merge key must be included in columns")
    quoted_columns = ", ".join(f"`{column}`" for column in columns)
    source_columns = ", ".join(f"S.`{column}`" for column in columns)
    return f"""
MERGE `{destination}` AS T
USING `{staging}` AS S
ON T.`{key_field}` = S.`{key_field}`
WHEN NOT MATCHED THEN
  INSERT ({quoted_columns})
  VALUES ({source_columns})
""".strip()


def _append_jsonl_from_gcs(
    *,
    destination: str,
    gcs_uri: str,
    schema: tuple[bigquery.SchemaField, ...],
    key_field: str,
    project_id: str,
    location: str,
    environment: str,
) -> dict:
    destination = _validated_table_id(destination, environment)
    client = bigquery.Client(project=project_id, location=location)
    dataset_id = ".".join(destination.split(".")[:2])
    dataset = client.get_dataset(dataset_id)
    labels = dataset.labels or {}
    if (
        labels.get("environment") != "shadow"
        or labels.get("work_package") != "wp04"
    ):
        raise RuntimeError(
            "WP-04 dataset must be labeled environment=shadow and work_package=wp04"
        )
    destination_table = client.get_table(destination)
    if _schema_shape(destination_table.schema) != _schema_shape(schema):
        raise RuntimeError(
            "WP-04 destination schema does not match the reviewed contract"
        )

    staging = f"{destination}_stage_{uuid.uuid4().hex}"
    table = bigquery.Table(staging, schema=schema)
    table.expires = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=2)
    client.create_table(table)
    try:
        load_config = bigquery.LoadJobConfig(
            schema=list(schema),
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        )
        load_job = client.load_table_from_uri(
            gcs_uri,
            staging,
            job_config=load_config,
        )
        load_job.result()
        staged_rows = client.get_table(staging).num_rows
        columns = [field.name for field in schema]
        merge_job = client.query(
            _merge_query(destination, staging, key_field, columns),
            location=location,
        )
        merge_job.result()
        return {
            "destination_table": destination,
            "dataset_labels": labels,
            "staged_rows": staged_rows,
            "inserted_rows": merge_job.num_dml_affected_rows or 0,
            "append_only": True,
            "production_change_allowed": False,
        }
    finally:
        client.delete_table(staging, not_found_ok=True)


def append_price_raw_from_gcs(
    *,
    destination: str,
    gcs_uri: str,
    project_id: str,
    location: str = "us-east1",
    environment: str = "shadow",
) -> dict:
    return _append_jsonl_from_gcs(
        destination=destination,
        gcs_uri=gcs_uri,
        schema=PRICE_SCHEMA,
        key_field="raw_revision_id",
        project_id=project_id,
        location=location,
        environment=environment,
    )


def append_corporate_actions_from_gcs(
    *,
    destination: str,
    gcs_uri: str,
    project_id: str,
    location: str = "us-east1",
    environment: str = "shadow",
) -> dict:
    return _append_jsonl_from_gcs(
        destination=destination,
        gcs_uri=gcs_uri,
        schema=ACTION_SCHEMA,
        key_field="action_id",
        project_id=project_id,
        location=location,
        environment=environment,
    )

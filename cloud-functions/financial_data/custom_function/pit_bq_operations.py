import logging
import re
import uuid

from google.cloud import bigquery


TABLE_ID = re.compile(r"^[A-Za-z0-9-]+\.[A-Za-z0-9_]+\.[A-Za-z0-9_]+$")
PIT_STATEMENT_COLUMNS = [
    "revision_id",
    "ticker",
    "cik",
    "mapping_version",
    "form_type",
    "accession_number",
    "source_record_id",
    "source_is_amendment",
    "filing_date",
    "source_published_at",
    "available_at",
    "period_end_date",
    "fiscal_year",
    "fiscal_quarter",
    "currency",
    "revenue",
    "gross_profit",
    "operating_income",
    "net_income",
    "eps_basic",
    "eps_diluted",
    "total_assets",
    "total_liabilities",
    "total_debt",
    "debt_current",
    "debt_noncurrent",
    "cash_and_equivalents",
    "shares_outstanding",
    "shareholders_equity",
    "operating_cash_flow",
    "free_cash_flow",
    "source",
    "source_url",
    "backtest_eligible",
    "eligibility_reason",
    "quality_status",
    "loaded_at",
]
PIT_STATEMENTS_SCHEMA = [
    bigquery.SchemaField("revision_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("ticker", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("cik", "STRING"),
    bigquery.SchemaField("mapping_version", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("form_type", "STRING"),
    bigquery.SchemaField("accession_number", "STRING"),
    bigquery.SchemaField("source_record_id", "STRING"),
    bigquery.SchemaField("source_is_amendment", "BOOLEAN", mode="REQUIRED"),
    bigquery.SchemaField("filing_date", "DATE"),
    bigquery.SchemaField("source_published_at", "TIMESTAMP"),
    bigquery.SchemaField("available_at", "TIMESTAMP"),
    bigquery.SchemaField("period_end_date", "DATE"),
    bigquery.SchemaField("fiscal_year", "INTEGER"),
    bigquery.SchemaField("fiscal_quarter", "INTEGER"),
    bigquery.SchemaField("currency", "STRING"),
    bigquery.SchemaField("revenue", "FLOAT"),
    bigquery.SchemaField("gross_profit", "FLOAT"),
    bigquery.SchemaField("operating_income", "FLOAT"),
    bigquery.SchemaField("net_income", "FLOAT"),
    bigquery.SchemaField("eps_basic", "FLOAT"),
    bigquery.SchemaField("eps_diluted", "FLOAT"),
    bigquery.SchemaField("total_assets", "FLOAT"),
    bigquery.SchemaField("total_liabilities", "FLOAT"),
    bigquery.SchemaField("total_debt", "FLOAT"),
    bigquery.SchemaField("debt_current", "FLOAT"),
    bigquery.SchemaField("debt_noncurrent", "FLOAT"),
    bigquery.SchemaField("cash_and_equivalents", "FLOAT"),
    bigquery.SchemaField("shares_outstanding", "FLOAT"),
    bigquery.SchemaField("shareholders_equity", "FLOAT"),
    bigquery.SchemaField("operating_cash_flow", "FLOAT"),
    bigquery.SchemaField("free_cash_flow", "FLOAT"),
    bigquery.SchemaField("source", "STRING"),
    bigquery.SchemaField("source_url", "STRING"),
    bigquery.SchemaField("backtest_eligible", "BOOLEAN", mode="REQUIRED"),
    bigquery.SchemaField("eligibility_reason", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("quality_status", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("loaded_at", "TIMESTAMP", mode="REQUIRED"),
]


def _validated_table_id(value):
    table_id = str(value or "").strip()
    if not TABLE_ID.fullmatch(table_id):
        raise ValueError("destination_table must be a fully-qualified BigQuery table ID")
    return table_id


def load_json_to_temp_table(client, gcs_uri, destination_table):
    destination_table = _validated_table_id(destination_table)
    temp_table = f"{destination_table}_temp_{uuid.uuid4().hex}"
    config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        schema=PIT_STATEMENTS_SCHEMA,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    try:
        client.load_table_from_uri(gcs_uri, temp_table, job_config=config).result()
    except Exception:
        client.delete_table(temp_table, not_found_ok=True)
        raise
    return temp_table


def _merge_query(destination_table, temp_table):
    destination_table = _validated_table_id(destination_table)
    temp_table = _validated_table_id(temp_table)
    insert_columns = ", ".join(f"`{name}`" for name in PIT_STATEMENT_COLUMNS)
    insert_values = ", ".join(f"S.`{name}`" for name in PIT_STATEMENT_COLUMNS)
    return f"""
    MERGE `{destination_table}` T
    USING (
      SELECT * EXCEPT(source_rank)
      FROM (
        SELECT
          source_rows.*,
          ROW_NUMBER() OVER (
            PARTITION BY revision_id
            ORDER BY loaded_at DESC, source_record_id DESC
          ) AS source_rank
        FROM `{temp_table}` source_rows
      )
      WHERE source_rank = 1
    ) S
    ON T.revision_id = S.revision_id
    WHEN NOT MATCHED THEN
      INSERT ({insert_columns})
      VALUES ({insert_values})
    """


def append_statement_revisions(destination_table, gcs_uri):
    """Atomically insert unseen immutable revisions; existing rows are never updated."""
    destination_table = _validated_table_id(destination_table)
    client = bigquery.Client()
    temp_table = load_json_to_temp_table(client, gcs_uri, destination_table)
    try:
        job = client.query(_merge_query(destination_table, temp_table))
        job.result()
        logging.info("PIT append completed for %s", destination_table)
        return job.num_dml_affected_rows or 0
    finally:
        client.delete_table(temp_table, not_found_ok=True)

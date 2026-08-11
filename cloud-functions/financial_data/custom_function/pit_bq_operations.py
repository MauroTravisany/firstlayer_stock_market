import logging
import uuid

from google.cloud import bigquery


PIT_STATEMENTS_SCHEMA = [
    bigquery.SchemaField("revision_id", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("ticker", "STRING", mode="REQUIRED"),
    bigquery.SchemaField("cik", "STRING"),
    bigquery.SchemaField("form_type", "STRING"),
    bigquery.SchemaField("accession_number", "STRING"),
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
    bigquery.SchemaField("backtest_eligible", "BOOLEAN"),
    bigquery.SchemaField("eligibility_reason", "STRING"),
    bigquery.SchemaField("loaded_at", "TIMESTAMP"),
]


def load_json_to_temp_table(client, gcs_uri, destination_table):
    temp_table = f"{destination_table}_temp_{uuid.uuid4().hex}"
    config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        schema=PIT_STATEMENTS_SCHEMA,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    client.load_table_from_uri(gcs_uri, temp_table, job_config=config).result()
    return temp_table


def append_statement_revisions(destination_table, gcs_uri):
    """Insert immutable revisions only. Existing revision_id rows are never updated."""
    client = bigquery.Client()
    temp_table = load_json_to_temp_table(client, gcs_uri, destination_table)
    try:
        query = f"""
        INSERT INTO `{destination_table}`
        SELECT S.*
        FROM `{temp_table}` S
        LEFT JOIN `{destination_table}` T USING (revision_id)
        WHERE T.revision_id IS NULL
        """
        job = client.query(query)
        job.result()
        logging.info("PIT append completed for %s", destination_table)
        return job.num_dml_affected_rows or 0
    finally:
        client.delete_table(temp_table, not_found_ok=True)

import logging
import uuid

from google.cloud import bigquery


STATEMENTS_SCHEMA = [
    bigquery.SchemaField("ticker", "STRING"),
    bigquery.SchemaField("fiscal_year", "INTEGER"),
    bigquery.SchemaField("fiscal_quarter", "INTEGER"),
    bigquery.SchemaField("period_end_date", "DATE"),
    bigquery.SchemaField("report_date", "DATE"),
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
    bigquery.SchemaField("shareholders_equity", "FLOAT"),
    bigquery.SchemaField("operating_cash_flow", "FLOAT"),
    bigquery.SchemaField("free_cash_flow", "FLOAT"),
    bigquery.SchemaField("source", "STRING"),
    bigquery.SchemaField("loaded_at", "TIMESTAMP"),
]

RATIOS_SCHEMA = [
    bigquery.SchemaField("ticker", "STRING"),
    bigquery.SchemaField("snapshot_date", "DATE"),
    bigquery.SchemaField("price", "FLOAT"),
    bigquery.SchemaField("market_cap", "FLOAT"),
    bigquery.SchemaField("enterprise_value", "FLOAT"),
    bigquery.SchemaField("pe_ratio", "FLOAT"),
    bigquery.SchemaField("forward_pe", "FLOAT"),
    bigquery.SchemaField("price_to_book", "FLOAT"),
    bigquery.SchemaField("price_to_sales", "FLOAT"),
    bigquery.SchemaField("ev_to_ebitda", "FLOAT"),
    bigquery.SchemaField("dividend_yield", "FLOAT"),
    bigquery.SchemaField("beta", "FLOAT"),
    bigquery.SchemaField("roe", "FLOAT"),
    bigquery.SchemaField("roa", "FLOAT"),
    bigquery.SchemaField("profit_margin", "FLOAT"),
    bigquery.SchemaField("gross_margin", "FLOAT"),
    bigquery.SchemaField("operating_margin", "FLOAT"),
    bigquery.SchemaField("debt_to_equity", "FLOAT"),
    bigquery.SchemaField("current_ratio", "FLOAT"),
    bigquery.SchemaField("source", "STRING"),
    bigquery.SchemaField("loaded_at", "TIMESTAMP"),
]


def load_json_to_temp_table(client, gcs_uri, destination_table, schema):
    temp_table = f"{destination_table}_temp_{uuid.uuid4().hex}"
    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        schema=schema,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )

    logging.info("Cargando %s en tabla temporal %s", gcs_uri, temp_table)
    load_job = client.load_table_from_uri(gcs_uri, temp_table, job_config=job_config)
    load_job.result()
    return temp_table


def merge_financial_statements(destination_table, gcs_uri):
    client = bigquery.Client()
    temp_table = load_json_to_temp_table(client, gcs_uri, destination_table, STATEMENTS_SCHEMA)

    try:
        query = f"""
        MERGE `{destination_table}` T
        USING `{temp_table}` S
        ON T.ticker = S.ticker
          AND T.fiscal_year = S.fiscal_year
          AND T.fiscal_quarter = S.fiscal_quarter
        WHEN MATCHED THEN UPDATE SET
          period_end_date = S.period_end_date,
          report_date = S.report_date,
          currency = S.currency,
          revenue = S.revenue,
          gross_profit = S.gross_profit,
          operating_income = S.operating_income,
          net_income = S.net_income,
          eps_basic = S.eps_basic,
          eps_diluted = S.eps_diluted,
          total_assets = S.total_assets,
          total_liabilities = S.total_liabilities,
          total_debt = S.total_debt,
          shareholders_equity = S.shareholders_equity,
          operating_cash_flow = S.operating_cash_flow,
          free_cash_flow = S.free_cash_flow,
          source = S.source,
          loaded_at = S.loaded_at
        WHEN NOT MATCHED THEN INSERT (
          ticker, fiscal_year, fiscal_quarter, period_end_date, report_date, currency,
          revenue, gross_profit, operating_income, net_income, eps_basic, eps_diluted,
          total_assets, total_liabilities, total_debt, shareholders_equity,
          operating_cash_flow, free_cash_flow, source, loaded_at
        ) VALUES (
          S.ticker, S.fiscal_year, S.fiscal_quarter, S.period_end_date, S.report_date, S.currency,
          S.revenue, S.gross_profit, S.operating_income, S.net_income, S.eps_basic, S.eps_diluted,
          S.total_assets, S.total_liabilities, S.total_debt, S.shareholders_equity,
          S.operating_cash_flow, S.free_cash_flow, S.source, S.loaded_at
        )
        """
        client.query(query).result()
    finally:
        client.delete_table(temp_table, not_found_ok=True)


def merge_financial_ratios(destination_table, gcs_uri):
    client = bigquery.Client()
    temp_table = load_json_to_temp_table(client, gcs_uri, destination_table, RATIOS_SCHEMA)

    try:
        query = f"""
        MERGE `{destination_table}` T
        USING `{temp_table}` S
        ON T.ticker = S.ticker AND T.snapshot_date = S.snapshot_date
        WHEN MATCHED THEN UPDATE SET
          price = S.price,
          market_cap = S.market_cap,
          enterprise_value = S.enterprise_value,
          pe_ratio = S.pe_ratio,
          forward_pe = S.forward_pe,
          price_to_book = S.price_to_book,
          price_to_sales = S.price_to_sales,
          ev_to_ebitda = S.ev_to_ebitda,
          dividend_yield = S.dividend_yield,
          beta = S.beta,
          roe = S.roe,
          roa = S.roa,
          profit_margin = S.profit_margin,
          gross_margin = S.gross_margin,
          operating_margin = S.operating_margin,
          debt_to_equity = S.debt_to_equity,
          current_ratio = S.current_ratio,
          source = S.source,
          loaded_at = S.loaded_at
        WHEN NOT MATCHED THEN INSERT (
          ticker, snapshot_date, price, market_cap, enterprise_value, pe_ratio, forward_pe,
          price_to_book, price_to_sales, ev_to_ebitda, dividend_yield, beta, roe, roa,
          profit_margin, gross_margin, operating_margin, debt_to_equity, current_ratio, source, loaded_at
        ) VALUES (
          S.ticker, S.snapshot_date, S.price, S.market_cap, S.enterprise_value, S.pe_ratio, S.forward_pe,
          S.price_to_book, S.price_to_sales, S.ev_to_ebitda, S.dividend_yield, S.beta, S.roe, S.roa,
          S.profit_margin, S.gross_margin, S.operating_margin, S.debt_to_equity, S.current_ratio, S.source, S.loaded_at
        )
        """
        client.query(query).result()
    finally:
        client.delete_table(temp_table, not_found_ok=True)

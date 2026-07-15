import json
import logging
import math
from datetime import date, datetime, timezone

import pandas as pd
import yfinance as yf

logging.basicConfig(level=logging.INFO)


def clean_value(value):
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if pd.isna(value):
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, (datetime, date)):
        return value.date().isoformat() if isinstance(value, datetime) else value.isoformat()
    return value


def statement_value(frame, column, names):
    if frame.empty or column not in frame.columns:
        return None

    for name in names:
        if name in frame.index:
            return clean_value(frame.at[name, column])
    return None


def fiscal_quarter(period_end_date):
    return ((period_end_date.month - 1) // 3) + 1


def build_financial_statement_rows(ticker, stock, info):
    financials = stock.quarterly_financials
    balance_sheet = stock.quarterly_balance_sheet
    cashflow = stock.quarterly_cashflow

    if financials.empty and balance_sheet.empty and cashflow.empty:
        return []

    columns = set()
    for frame in (financials, balance_sheet, cashflow):
        if not frame.empty:
            columns.update(frame.columns)

    rows = []
    loaded_at = datetime.now(timezone.utc).isoformat()
    currency = info.get("financialCurrency") or info.get("currency")

    for column in sorted(columns, reverse=True):
        period_end = pd.Timestamp(column).date()
        rows.append(
            {
                "ticker": ticker,
                "fiscal_year": period_end.year,
                "fiscal_quarter": fiscal_quarter(period_end),
                "period_end_date": period_end.isoformat(),
                "report_date": None,
                "currency": currency,
                "revenue": statement_value(financials, column, ["Total Revenue"]),
                "gross_profit": statement_value(financials, column, ["Gross Profit"]),
                "operating_income": statement_value(financials, column, ["Operating Income"]),
                "net_income": statement_value(financials, column, ["Net Income"]),
                "eps_basic": statement_value(financials, column, ["Basic EPS"]),
                "eps_diluted": statement_value(financials, column, ["Diluted EPS"]),
                "total_assets": statement_value(balance_sheet, column, ["Total Assets"]),
                "total_liabilities": statement_value(balance_sheet, column, ["Total Liabilities Net Minority Interest", "Total Liab"]),
                "total_debt": statement_value(balance_sheet, column, ["Total Debt"]),
                "shareholders_equity": statement_value(
                    balance_sheet,
                    column,
                    ["Stockholders Equity", "Total Equity Gross Minority Interest", "Total Stockholder Equity"],
                ),
                "operating_cash_flow": statement_value(cashflow, column, ["Operating Cash Flow", "Total Cash From Operating Activities"]),
                "free_cash_flow": statement_value(cashflow, column, ["Free Cash Flow"]),
                "source": "yfinance",
                "loaded_at": loaded_at,
            }
        )

    return rows


def build_ratio_snapshot_row(ticker, info, snapshot_date):
    return {
        "ticker": ticker,
        "snapshot_date": snapshot_date.isoformat(),
        "price": clean_value(info.get("currentPrice") or info.get("regularMarketPrice")),
        "market_cap": clean_value(info.get("marketCap")),
        "enterprise_value": clean_value(info.get("enterpriseValue")),
        "pe_ratio": clean_value(info.get("trailingPE")),
        "forward_pe": clean_value(info.get("forwardPE")),
        "price_to_book": clean_value(info.get("priceToBook")),
        "price_to_sales": clean_value(info.get("priceToSalesTrailing12Months")),
        "ev_to_ebitda": clean_value(info.get("enterpriseToEbitda")),
        "dividend_yield": clean_value(info.get("dividendYield")),
        "beta": clean_value(info.get("beta")),
        "roe": clean_value(info.get("returnOnEquity")),
        "roa": clean_value(info.get("returnOnAssets")),
        "profit_margin": clean_value(info.get("profitMargins")),
        "gross_margin": clean_value(info.get("grossMargins")),
        "operating_margin": clean_value(info.get("operatingMargins")),
        "debt_to_equity": clean_value(info.get("debtToEquity")),
        "current_ratio": clean_value(info.get("currentRatio")),
        "source": "yfinance",
        "loaded_at": datetime.now(timezone.utc).isoformat(),
    }


def write_json_lines(path, rows):
    with open(path, "w", encoding="utf-8") as file:
        for row in rows:
            file.write(json.dumps(row) + "\n")


def save_financial_data_to_json(ticker, snapshot_date):
    stock = yf.Ticker(ticker)
    info = stock.info or {}

    statements = build_financial_statement_rows(ticker, stock, info)
    ratios = [build_ratio_snapshot_row(ticker, info, snapshot_date)]

    statements_file = f"{ticker}_financial_statements_{snapshot_date}.json" if statements else None
    ratios_file = f"{ticker}_financial_ratios_{snapshot_date}.json"

    if statements_file:
        write_json_lines(statements_file, statements)
    write_json_lines(ratios_file, ratios)

    logging.info("Generadas %s filas de statements y %s filas de ratios para %s", len(statements), len(ratios), ticker)

    return {
        "statements_file": statements_file,
        "ratios_file": ratios_file,
        "statements_count": len(statements),
        "ratios_count": len(ratios),
    }

import json
import logging
from collections import Counter
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pandas as pd
import requests
import yfinance as yf


MACRO_SYMBOLS = {
    "SPY": "us_equity_spy",
    "QQQ": "growth_tech_qqq",
    "IWM": "small_caps_iwm",
    "^VIX": "volatility_vix",
    "UUP": "usd_dollar_uup",
    "EURUSD=X": "eur_usd",
    "^TNX": "us_10y_yield",
    "CL=F": "wti_oil",
    "GC=F": "gold",
    "XLE": "energy_equity_xle",
    "BTC-USD": "bitcoin",
    "ETH-USD": "ethereum",
}

NEWS_TOPICS = {
    "geopolitical_conflict": '(war OR conflict OR missile OR sanctions OR invasion OR geopolitical OR "red sea" OR taiwan)',
    "rates_inflation": '("interest rates" OR inflation OR "central bank" OR "treasury yields" OR "Federal Reserve")',
    "usd_fx": '("US dollar" OR "dollar index" OR EURUSD OR "foreign exchange")',
    "crypto_regulation": '(bitcoin OR ethereum OR crypto) (regulation OR ETF OR SEC OR exchange OR hack)',
    "ai_semiconductors": '(semiconductor OR Nvidia OR ASML OR chips OR "artificial intelligence") (export OR demand OR supply OR earnings)',
    "energy_oil": '(oil OR crude OR OPEC OR energy) (supply OR sanctions OR conflict OR demand)',
}


def current_slot(time_zone):
    now = datetime.now(ZoneInfo(time_zone))
    slot_hour = (now.hour // 4) * 4
    slot = now.replace(hour=slot_hour, minute=0, second=0, microsecond=0)
    return slot


def _pct(current, previous):
    if current is None or previous in (None, 0):
        return None
    return float(current / previous - 1)


def fetch_market_rows(slot):
    tickers = list(MACRO_SYMBOLS.keys())
    data = yf.download(
        tickers=" ".join(tickers),
        period="90d",
        interval="1d",
        auto_adjust=False,
        progress=False,
        threads=True,
        timeout=20,
    )
    rows = []
    loaded_at = datetime.now(ZoneInfo("UTC")).isoformat()
    slot_utc = slot.astimezone(ZoneInfo("UTC")).isoformat()
    for symbol in tickers:
        try:
            close_series = data["Close"][symbol].dropna()
            if close_series.empty:
                logging.warning("No macro data for %s", symbol)
                continue
            close = float(close_series.iloc[-1])
            previous = float(close_series.iloc[-2]) if len(close_series) > 1 else None
            prev_5 = float(close_series.iloc[-6]) if len(close_series) > 5 else None
            prev_20 = float(close_series.iloc[-21]) if len(close_series) > 20 else None
            rows.append(
                {
                    "snapshot_slot": slot_utc,
                    "snapshot_date": slot.date().isoformat(),
                    "signal_hour": slot.time().strftime("%H:%M:%S"),
                    "symbol": symbol,
                    "factor_name": MACRO_SYMBOLS[symbol],
                    "close": close,
                    "previous_close": previous,
                    "return_1d": _pct(close, previous),
                    "return_5d": _pct(close, prev_5),
                    "return_20d": _pct(close, prev_20),
                    "source": "yfinance_yahoo_public",
                    "loaded_at": loaded_at,
                }
            )
        except Exception as exc:
            logging.warning("Failed macro symbol %s: %s", symbol, exc)
    return rows


def _top_source_countries(articles):
    countries = Counter([item.get("sourcecountry") for item in articles if item.get("sourcecountry")])
    return json.dumps(countries.most_common(5), ensure_ascii=True)


def _sample_titles(articles):
    titles = [item.get("title") for item in articles if item.get("title")]
    return json.dumps(titles[:5], ensure_ascii=True)


def fetch_news_rows(slot, timespan="4H", maxrecords=75):
    rows = []
    loaded_at = datetime.now(ZoneInfo("UTC")).isoformat()
    slot_utc = slot.astimezone(ZoneInfo("UTC")).isoformat()
    for topic, query in NEWS_TOPICS.items():
        try:
            response = requests.get(
                "https://api.gdeltproject.org/api/v2/doc/doc",
                params={
                    "query": query,
                    "mode": "ArtList",
                    "format": "json",
                    "timespan": timespan,
                    "maxrecords": maxrecords,
                },
                timeout=25,
            )
            response.raise_for_status()
            payload = response.json()
            articles = payload.get("articles") or []
            rows.append(
                {
                    "snapshot_slot": slot_utc,
                    "snapshot_date": slot.date().isoformat(),
                    "signal_hour": slot.time().strftime("%H:%M:%S"),
                    "topic": topic,
                    "query": query,
                    "article_count": len(articles),
                    "top_source_countries": _top_source_countries(articles),
                    "sample_titles": _sample_titles(articles),
                    "source": "gdelt_doc_public",
                    "loaded_at": loaded_at,
                }
            )
        except Exception as exc:
            logging.warning("Failed news topic %s: %s", topic, exc)
            rows.append(
                {
                    "snapshot_slot": slot_utc,
                    "snapshot_date": slot.date().isoformat(),
                    "signal_hour": slot.time().strftime("%H:%M:%S"),
                    "topic": topic,
                    "query": query,
                    "article_count": None,
                    "top_source_countries": "[]",
                    "sample_titles": json.dumps([f"ERROR: {exc}"], ensure_ascii=True),
                    "source": "gdelt_doc_public",
                    "loaded_at": loaded_at,
                }
            )
    return rows


def fetch_market_history_rows(start_date=None, end_date=None, years=5, time_zone="America/Santiago"):
    end = pd.to_datetime(end_date).date() if end_date else datetime.now(ZoneInfo(time_zone)).date()
    start = pd.to_datetime(start_date).date() if start_date else end - timedelta(days=365 * int(years))
    if start > end:
        raise ValueError("start_date cannot be after end_date")

    tickers = list(MACRO_SYMBOLS.keys())
    data = yf.download(
        tickers=" ".join(tickers),
        start=start.isoformat(),
        end=(end + timedelta(days=1)).isoformat(),
        interval="1d",
        auto_adjust=False,
        progress=False,
        threads=True,
        timeout=45,
    )
    rows = []
    loaded_at = datetime.now(ZoneInfo("UTC")).isoformat()
    local_tz = ZoneInfo(time_zone)

    for symbol in tickers:
        try:
            close_series = data["Close"][symbol].dropna()
            if close_series.empty:
                logging.warning("No historical macro data for %s", symbol)
                continue
            close_series = close_series.sort_index()
            for idx, close_value in enumerate(close_series):
                snapshot_date = pd.to_datetime(close_series.index[idx]).date()
                previous = float(close_series.iloc[idx - 1]) if idx >= 1 else None
                prev_5 = float(close_series.iloc[idx - 5]) if idx >= 5 else None
                prev_20 = float(close_series.iloc[idx - 20]) if idx >= 20 else None
                slot = datetime.combine(snapshot_date, datetime.min.time(), tzinfo=local_tz)
                rows.append(
                    {
                        "snapshot_slot": slot.astimezone(ZoneInfo("UTC")).isoformat(),
                        "snapshot_date": snapshot_date.isoformat(),
                        "signal_hour": "00:00:00",
                        "symbol": symbol,
                        "factor_name": MACRO_SYMBOLS[symbol],
                        "close": float(close_value),
                        "previous_close": previous,
                        "return_1d": _pct(float(close_value), previous),
                        "return_5d": _pct(float(close_value), prev_5),
                        "return_20d": _pct(float(close_value), prev_20),
                        "source": "yfinance_yahoo_public_history",
                        "loaded_at": loaded_at,
                    }
                )
        except Exception as exc:
            logging.warning("Failed historical macro symbol %s: %s", symbol, exc)
    return rows


def _safe_float(value):
    if value is None or pd.isna(value):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _event_status(days_to_earnings, surprise_pct):
    if days_to_earnings is None:
        return "NO_EARNINGS_DATA"
    if days_to_earnings < -5:
        return "OLD_RESULT"
    if days_to_earnings <= 0:
        if surprise_pct is None:
            return "RECENT_RESULT"
        if surprise_pct >= 5:
            return "RECENT_POSITIVE_SURPRISE"
        if surprise_pct <= -5:
            return "RECENT_NEGATIVE_SURPRISE"
        return "RECENT_INLINE_RESULT"
    if days_to_earnings <= 3:
        return "EARNINGS_IMMINENT"
    if days_to_earnings <= 14:
        return "PRE_EARNINGS_WINDOW"
    return "EARNINGS_FAR"


def _empty_earnings_row(slot, ticker, loaded_at, message):
    slot_utc = slot.astimezone(ZoneInfo("UTC")).isoformat()
    return {
        "snapshot_slot": slot_utc,
        "snapshot_date": slot.date().isoformat(),
        "signal_hour": slot.time().strftime("%H:%M:%S"),
        "ticker": ticker,
        "earnings_date": None,
        "days_to_earnings": None,
        "earnings_time": message[:100],
        "eps_estimate": None,
        "reported_eps": None,
        "surprise_pct": None,
        "event_status": "NO_EARNINGS_DATA",
        "source": "yfinance_yahoo_public",
        "loaded_at": loaded_at,
    }


def fetch_earnings_rows(slot, tickers, limit=8):
    rows = []
    loaded_at = datetime.now(ZoneInfo("UTC")).isoformat()
    slot_utc = slot.astimezone(ZoneInfo("UTC")).isoformat()
    stock_tickers = [ticker for ticker in tickers if not ticker.endswith("-USD")]

    for ticker in stock_tickers:
        try:
            earnings = yf.Ticker(ticker).get_earnings_dates(limit=limit)
            if earnings is None or earnings.empty:
                rows.append(_empty_earnings_row(slot, ticker, loaded_at, "Sin calendario en Yahoo"))
                continue

            normalized = earnings.reset_index()
            date_col = normalized.columns[0]
            normalized["earnings_dt"] = pd.to_datetime(normalized[date_col], errors="coerce", utc=True)
            normalized = normalized.dropna(subset=["earnings_dt"])
            if normalized.empty:
                rows.append(_empty_earnings_row(slot, ticker, loaded_at, "Calendario Yahoo sin fechas validas"))
                continue

            normalized["days_abs"] = (normalized["earnings_dt"].dt.date - slot.date()).apply(lambda delta: abs(delta.days))
            event = normalized.sort_values("days_abs").iloc[0]
            earnings_date = event["earnings_dt"].date()
            days_to_earnings = (earnings_date - slot.date()).days
            surprise_pct = _safe_float(event.get("Surprise(%)"))

            rows.append(
                {
                    "snapshot_slot": slot_utc,
                    "snapshot_date": slot.date().isoformat(),
                    "signal_hour": slot.time().strftime("%H:%M:%S"),
                    "ticker": ticker,
                    "earnings_date": earnings_date.isoformat(),
                    "days_to_earnings": int(days_to_earnings),
                    "earnings_time": str(event.get("Earnings Date") or event.get("Hour") or "")[:100],
                    "eps_estimate": _safe_float(event.get("EPS Estimate")),
                    "reported_eps": _safe_float(event.get("Reported EPS")),
                    "surprise_pct": surprise_pct,
                    "event_status": _event_status(days_to_earnings, surprise_pct),
                    "source": "yfinance_yahoo_public",
                    "loaded_at": loaded_at,
                }
            )
        except Exception as exc:
            logging.warning("Failed earnings calendar for %s: %s", ticker, exc)
            rows.append(_empty_earnings_row(slot, ticker, loaded_at, f"ERROR: {exc}"))
    return rows

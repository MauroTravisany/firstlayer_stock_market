import json
import logging
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

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

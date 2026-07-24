import base64
import hashlib
import json
import logging
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO)


CRYPTO_INTERVAL = "1h"
CRYPTO_OUTPUT_FREQUENCY = "4h"
DEFAULT_INTERVAL = "15m"


def generate_unique_id(ticker, fecha, hora):
    id_string = f"{ticker}_{fecha}_{hora}"
    digest = hashlib.md5(id_string.encode("utf-8")).digest()
    return base64.b64encode(digest).decode("ascii")


def _normalize_market_data(stock_data, asset_type):
    if str(asset_type).upper() != "CRYPTO":
        return stock_data

    if stock_data.empty:
        return stock_data

    agg = {
        "Open": "first",
        "High": "max",
        "Low": "min",
        "Close": "last",
        "Volume": "sum",
    }
    return stock_data.resample(CRYPTO_OUTPUT_FREQUENCY).agg(agg).dropna(subset=["Open", "High", "Low", "Close"])


def save_data_to_json(ticker, output_file, target_date, asset_type="STOCK", end_date=None):
    import yfinance as yf

    end_date = end_date or target_date + timedelta(days=1)
    asset_type = str(asset_type or "STOCK").upper()
    interval = CRYPTO_INTERVAL if asset_type == "CRYPTO" else DEFAULT_INTERVAL

    try:
        try:
            stock_data = yf.Ticker(ticker).history(
                start=target_date,
                end=end_date,
                interval=interval,
                auto_adjust=False,
            )
            stock_data = _normalize_market_data(stock_data, asset_type)
        except ValueError as exc:
            raise RuntimeError(
                f"Yahoo Finance did not return valid price data for {ticker} on {target_date}. "
                "Try a recent market day or redeploy with the updated yfinance dependency."
            ) from exc

        if stock_data.empty:
            raise ValueError(
                f"No data returned for ticker {ticker} between {target_date} and {end_date}. "
                "Use a valid trading day within yfinance intraday history."
            )

        stock_data["volatilidad"] = ((stock_data["High"] - stock_data["Low"]) / stock_data["Open"]) * 100
        prev_close = None

        with open(output_file, "w", encoding="utf-8") as file:
            for index, row in stock_data.iterrows():
                fecha = index.date()
                hora = index.time()
                valor_promedio = (row["Open"] + row["Close"]) / 2
                pct_change = None

                if prev_close is not None:
                    pct_change = ((row["Close"] - prev_close) / prev_close) * 100
                prev_close = row["Close"]

                message = {
                    "id": generate_unique_id(ticker, fecha, hora),
                    "fecha": str(fecha),
                    "hora": str(hora),
                    "ticker": str(ticker),
                    "open": row["Open"],
                    "close": row["Close"],
                    "high": row["High"],
                    "low": row["Low"],
                    "valor_promedio": valor_promedio,
                    "volumen": int(row["Volume"]),
                    "pct_change": pct_change,
                    "volatilidad": row["volatilidad"],
                    "fecha_creacion": datetime.now().isoformat(),
                }

                file.write(json.dumps(message) + "\n")

        logging.info("Datos para %s guardados en %s", ticker, output_file)
        return len(stock_data)
    except Exception:
        logging.exception("Error al procesar los datos de %s", ticker)
        raise

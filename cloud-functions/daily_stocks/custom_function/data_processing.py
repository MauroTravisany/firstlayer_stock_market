import base64
import hashlib
import json
import logging
from datetime import datetime, timedelta

logging.basicConfig(level=logging.INFO)


def generate_unique_id(ticker, fecha, hora):
    id_string = f"{ticker}_{fecha}_{hora}"
    digest = hashlib.md5(id_string.encode("utf-8")).digest()
    return base64.b64encode(digest).decode("ascii")


def save_data_to_json(ticker, output_file, target_date):
    import yfinance as yf

    try:
        stock_data = yf.Ticker(ticker).history(
            start=target_date,
            end=target_date + timedelta(days=1),
            interval="15m",
        )
        if stock_data.empty:
            raise ValueError(f"No data returned for ticker: {ticker}")

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
    except Exception:
        logging.exception("Error al procesar los datos de %s", ticker)
        raise

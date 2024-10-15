import yfinance as yf
import json
import hashlib
from datetime import  datetime, timedelta
import logging

# Configurar el logging para registrar errores
logging.basicConfig(level=logging.INFO)

# Función para generar un identificador único (hash basado en ticker, fecha y hora)
def generate_unique_id(ticker, fecha, hora):
    id_string = f"{str(ticker)}_{str(fecha)}_{str(hora)}"
    unique_id = hashlib.md5(id_string.encode()).hexdigest()  # Genera un hash MD5 como ID único
    return unique_id


# Función para generar los datos de acciones en un archivo JSON
def save_data_to_json(ticker, output_file, target_date):
    try:
        stock_data = yf.Ticker(ticker).history(start=target_date, end=target_date + timedelta(days=1), interval="15m")
        if stock_data.empty:
            raise ValueError(f"No data returned for ticker: {ticker}")
        stock_data['volatilidad'] = ((stock_data['High'] - stock_data['Low']) / stock_data['Open']) * 100
        prev_close = None

        with open(output_file, 'w') as f:
            for index, row in stock_data.iterrows():
                fecha = index.date()
                hora = index.time()
                valor_promedio = (row['Open'] + row['Close']) / 2
                pct_change = None

                if prev_close is not None:
                    pct_change = ((row['Close'] - prev_close) / prev_close) * 100
                prev_close = row['Close']

                # Generar ID único basado en ticker, fecha y hora
                unique_id = generate_unique_id(ticker, fecha, hora)
                fecha_creacion = datetime.now().isoformat() 

                message = {
                    "id": unique_id,  # ID único para evitar duplicados
                    "fecha": str(fecha),
                    "hora": str(hora),
                    "ticker": str(ticker),
                    "open": row['Open'],
                    "close": row['Close'],
                    "high": row['High'],
                    "low": row['Low'],
                    "valor_promedio": valor_promedio,
                    "volumen": int(row['Volume']),
                    "pct_change": pct_change,
                    "volatilidad": row['volatilidad'],
                    "fecha_creacion": fecha_creacion                 
                }

                f.write(json.dumps(message) + '\n')
                logging.info(f"Datos para {ticker} guardados en {output_file}")
    except Exception as e:
        logging.error(f"Error al procesar los datos de {ticker}: {str(e)}")
        raise 
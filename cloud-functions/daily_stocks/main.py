import sys
import os
import logging
import json
from datetime import datetime
from functions_framework import create_app  # Framework para ejecutar en Cloud Run

# Añadir el directorio actual al path de Python para importaciones
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(os.path.expanduser("~/.local/lib/python3.12/site-packages"))
from custom_function.data_processing import save_data_to_json
from custom_function.gcs_operations import upload_to_gcs
from custom_function.bq_operations import load_data_to_bigquery

# Importar configuraciones y funciones personalizadas
from conf.conf import bucket_name, bq_table  # Ya no necesitas importar tickers y target_date desde conf.py

# Cargar las variables de entorno para tickers y la fecha objetivo
tickers = os.environ.get('TICKERS', 'AAPL').split(",")  # Por defecto, usa 'AAPL' si no se proporciona la variable
target_date_str = os.environ.get('TARGET_DATE')

# Convertir TARGET_DATE en un objeto datetime (si no se proporciona, utiliza la fecha actual)
if target_date_str:
    target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
else:
    target_date = datetime.today().date()

# Configurar el logging para capturar los errores en Cloud Logging
logging.basicConfig(level=logging.INFO)

# Función para procesar cada ticker individualmente, recibiendo las rutas desde conf
def process_ticker(ticker, bucket_name, bq_table, target_date):
    try:
        output_file = f"{ticker}_{str(target_date)}.json"
        gcs_output_path = f"gs://{bucket_name}/{ticker}/{output_file}"

        # Aquí llamas a las funciones personalizadas (ejemplo)
        # Generar datos de acciones en un archivo JSON para la fecha objetivo
        save_data_to_json(ticker, output_file, target_date)
        
        # Subir el archivo a Google Cloud Storage
        upload_to_gcs(bucket_name, output_file, f"{ticker}/{output_file}")
        
        # Cargar los datos en BigQuery
        load_data_to_bigquery(bq_table, gcs_output_path)
        
        logging.info(f"Proceso completado exitosamente para {ticker} en la fecha {target_date}")
        return {"status": "success", "ticker": ticker, "message": "Proceso completado con éxito"}

    except Exception as e:
        logging.error(f"Error al procesar el ticker {ticker} para la fecha {target_date}: {str(e)}")
        raise

# Función HTTP principal para Cloud Run y Functions Framework
def main(request):
    """
    Punto de entrada para Google Cloud Run.
    Este método maneja solicitudes HTTP y procesa tickers.
    """
    request_json = request.get_json(silent=True)

    # Permitir que los tickers se pasen también en la solicitud (opcional)
    tickers_input = request_json.get("tickers", tickers)

    resultados = []
    
    for ticker in tickers_input:
        try:
            logging.info(f"Iniciando proceso para el ticker {ticker} en la fecha {target_date}")
            resultado = process_ticker(ticker, bucket_name, bq_table, target_date)
            resultados.append(resultado)
        except Exception as e:
            logging.error(f"El proceso falló para el ticker {ticker} en la fecha {target_date}: {str(e)}")
            resultados.append({"status": "error", "ticker": ticker, "message": str(e)})

    return json.dumps(resultados), 200, {'Content-Type': 'application/json'}


# Ejecutar la aplicación con Functions Framework
if __name__ == '__main__':
    port = int(os.environ.get("PORT", 8080))  # Usamos el puerto 8080 que Cloud Run requiere
    app = create_app("main")  # Aquí definimos el nombre de la función que se ejecutará
    app.run(host="0.0.0.0", port=port)

import sys
import os
import logging
import json
from datetime import datetime
from google.cloud import storage, bigquery

# Añadir el directorio actual al path de Python para importaciones
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Importar configuraciones y funciones personalizadas
from conf.conf import bucket_name, bq_table, tickers, target_date  # Las variables centrales desde conf
from custom_function.data_processing import save_data_to_json
from custom_function.gcs_operations import upload_to_gcs
from custom_function.bq_operations import load_data_to_bigquery

# Configurar el logging para capturar los errores en Cloud Logging
logging.basicConfig(level=logging.INFO)

# Función para procesar cada ticker individualmente, recibiendo las rutas desde conf
def process_ticker(ticker, bucket_name, bq_table, target_date):
    try:
        # Generar el nombre del archivo de salida y la ruta en GCS usando las configuraciones centralizadas
        output_file = f"{ticker}_{str(target_date)}.json"
        gcs_output_path = f"gs://{bucket_name}/{ticker}/{output_file}"

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
        raise  # Relanzar el error para que el flujo principal capture y decida si continuar

# Función HTTP principal para Google Cloud Functions
def main(request):
    """
    Punto de entrada para Google Cloud Functions.
    Este método maneja solicitudes HTTP y procesa tickers.
    """
    # Extraer el cuerpo de la solicitud (request body)
    request_json = request.get_json(silent=True)

    # Si se proporcionan tickers en la solicitud, procesarlos, de lo contrario usar la lista por defecto
    if request_json and "tickers" in request_json:
        tickers_input = request_json["tickers"]
    else:
        tickers_input = tickers  # Usa la lista de tickers desde la configuración si no se proporciona entrada

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

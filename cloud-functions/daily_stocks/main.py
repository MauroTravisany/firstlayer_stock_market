import sys
import os
import logging

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

    except Exception as e:
        logging.error(f"Error al procesar el ticker {ticker} para la fecha {target_date}: {str(e)}")
        raise  # Relanzar el error para que el flujo principal capture y decida si continuar

# Función principal para manejar múltiples tickers
def main():
    # Procesar cada ticker individualmente utilizando las variables de configuración
    for ticker in tickers:
        try:
            logging.info(f"Iniciando proceso para el ticker {ticker} en la fecha {target_date}")
            process_ticker(ticker, bucket_name, bq_table, target_date)
        except Exception as e:
            logging.error(f"El proceso falló para el ticker {ticker} en la fecha {target_date}: {str(e)}")
            # Continuar con los otros tickers aunque uno falle

# Ejecutar la función principal si este archivo se ejecuta directamente
if __name__ == "__main__":
    main()

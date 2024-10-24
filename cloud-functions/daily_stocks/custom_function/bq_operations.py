import logging
from google.cloud import bigquery

def load_data_to_bigquery(bq_table, gcs_output_path):
    client = bigquery.Client()

    # Configuración para escribir en modo APPEND
    job_config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
        autodetect=True,
        write_disposition=bigquery.WriteDisposition.WRITE_APPEND
    )

    # Definir tabla temporal
    temp_table = f"{bq_table}_temp"
    
    try:
        # Cargar datos en la tabla temporal
        logging.info(f"Cargando datos en la tabla temporal {temp_table}")
        load_job = client.load_table_from_uri(gcs_output_path, temp_table, job_config=job_config)
        load_job.result()  # Esperar a que termine la carga
        logging.info(f"Datos cargados exitosamente en la tabla temporal {temp_table}")

    except Exception as e:
        logging.error(f"Error al cargar datos en la tabla temporal {temp_table}: {str(e)}")
        return  # Finalizar el proceso si falla la carga de datos

    try:
        # Ejecutar MERGE en BigQuery
        logging.info(f"Ejecutando MERGE entre {temp_table} y {bq_table}")
        merge_query = f"""
        MERGE `{bq_table}` T
        USING `{temp_table}` S
        ON T.id = S.id
        WHEN MATCHED THEN
          UPDATE SET
            T.fecha = S.fecha,
            T.hora = S.hora,
            T.ticker = S.ticker,
            T.open = S.open,
            T.close = S.close,
            T.high = S.high,
            T.low = S.low,
            T.valor_promedio = S.valor_promedio,
            T.volumen = S.volumen,
            T.pct_change = S.pct_change,
            T.volatilidad = S.volatilidad,
            T.fecha_creacion = S.fecha_creacion
        WHEN NOT MATCHED THEN
          INSERT (id, fecha, hora, ticker, open, close, high, low, valor_promedio, volumen, pct_change, volatilidad, fecha_creacion)
          VALUES(S.id, S.fecha, S.hora, S.ticker, S.open, S.close, S.high, S.low, S.valor_promedio, S.volumen, S.pct_change, S.volatilidad, S.fecha_creacion)
        """
        client.query(merge_query).result()
        logging.info(f"MERGE completado exitosamente entre {temp_table} y {bq_table}")
        
    except Exception as e:
        logging.error(f"Error durante la ejecución del MERGE entre {temp_table} y {bq_table}: {str(e)}")
        return  

    try:
        # Limpiar tabla temporal
        logging.info(f"Eliminando la tabla temporal {temp_table}")
        client.delete_table(temp_table, not_found_ok=True)
        logging.info(f"Tabla temporal {temp_table} eliminada exitosamente")

    except Exception as e:
        logging.error(f"Error al eliminar la tabla temporal {temp_table}: {str(e)}")

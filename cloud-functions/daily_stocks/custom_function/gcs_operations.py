from google.cloud import storage
import os
import logging

# Función para subir el archivo a Google Cloud Storage
def upload_to_gcs(bucket_name, source_file_name, destination_blob_name):
    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(destination_blob_name)
        blob.upload_from_filename(source_file_name)
        logging.info(f"Archivo {source_file_name} subido exitosamente a {destination_blob_name} en GCS.")
        if os.path.exists(destination_blob_name):
            os.remove(source_file_name)  # Eliminar el archivo local
            logging.info(f"Archivo local '{source_file_name}' eliminado.")
        else:
            logging.warning(f"Archivo local '{source_file_name}' no encontrado.")
        print(f"Archivo {source_file_name} subido a {destination_blob_name} en GCS.")
    except Exception as e:
        logging.info(bucket_name)
        logging.error(f"Error al subir {source_file_name} a GCS: {str(e)}")
        raise  # Relanzar la excepción para que el flujo principal decida cómo proceder
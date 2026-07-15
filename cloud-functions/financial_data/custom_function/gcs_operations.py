import logging
import os

from google.cloud import storage


def upload_to_gcs(bucket_name, source_file_name, destination_blob_name):
    try:
        storage_client = storage.Client()
        bucket = storage_client.bucket(bucket_name)
        blob = bucket.blob(destination_blob_name)
        blob.upload_from_filename(source_file_name)
        logging.info("Archivo %s subido a gs://%s/%s", source_file_name, bucket_name, destination_blob_name)

        if os.path.exists(source_file_name):
            os.remove(source_file_name)
    except Exception:
        logging.exception("Error al subir %s a GCS", source_file_name)
        raise

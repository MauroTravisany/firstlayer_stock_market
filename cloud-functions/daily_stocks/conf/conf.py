import os
from datetime import date, datetime
from google.cloud import secretmanager

# Función para acceder a los secretos almacenados en Secret Manager
def access_secret_version(secret_id, version_id="latest"):
    client = secretmanager.SecretManagerServiceClient()
    name = f"projects/{os.environ.get('PROJECT_ID')}/secrets/{secret_id}/versions/{version_id}"
    response = client.access_secret_version(name=name)
    secret_value = response.payload.data.decode("UTF-8")
    return secret_value

# Cargar variables sensibles desde Google Secret Manager
bucket_name = access_secret_version("bucket_name")
project_id = access_secret_version("project_id")
dataset_id = access_secret_version("dataset_id")
table_id = access_secret_version("table_id")

# Generar la tabla de BigQuery con los datos obtenidos
bq_table = f"{project_id}.{dataset_id}.{table_id}"

# Cargar tickers desde las variables de entorno (si no se suministra, usar 'AAPL' por defecto)
tickers = os.environ.get('TICKERS', 'AAPL').split(";")

# Cargar la fecha objetivo desde una variable de entorno o usar la fecha actual
target_date_str = os.environ.get('TARGET_DATE')
if target_date_str:
    try:
        # Convertir la cadena en un objeto datetime
        target_date = datetime.strptime(target_date_str, "%Y-%m-%d").date()
    except ValueError:
        print(f"Formato de fecha incorrecto: {target_date_str}. Se usará la fecha actual.")
        target_date = date.today()
else:
    target_date = date.today()

# Primera capa de ingesta de datos para sistema de acciones bursátiles (proceso diario)

## Proyecto de Integración de Google Cloud Functions con BigQuery y Google Cloud Storage

Este proyecto representa la primera capa de un pipeline ETL (**Extract, Transform, Load**) diseñado para extraer datos financieros desde fuentes externas, realizar transformaciones básicas, y cargar los datos en **Google Cloud Storage** y **BigQuery** para análisis posterior.

### Fases del pipeline:

#### 1. Extract (Extracción):
Los datos de acciones financieras son extraídos utilizando la API de **yfinance**, que proporciona información en tiempo real y datos históricos de los precios de las acciones.

#### 2. Transform (Transformación):
Durante la extracción de los datos, se realizan transformaciones básicas, como el cálculo de la volatilidad y la generación de un ID único basado en un hash de los valores.

#### 3. Load (Carga):
Los datos transformados se almacenan en **Google Cloud Storage** como archivos JSON. Simultáneamente, los datos se cargan en **Google BigQuery**, lo que permite realizar análisis y consultas avanzadas sobre los datos.

### Evolución futura:

Este pipeline está diseñado para ser escalable y modular. En futuras iteraciones, se pueden agregar nuevas fuentes de datos, realizar transformaciones más complejas, o incluso automatizar análisis financieros avanzados.

- **Ejecución programada**: Configurar **Cloud Scheduler** para que ejecute el pipeline de forma automática en intervalos regulares (diarios o por hora).
- **Enriquecimiento de datos**: Agregar más fuentes de datos o combinar los datos con datasets externos.
- **Orquestación avanzada**: Integrar un sistema de orquestación como **Apache Airflow** o **Google Cloud Composer** para gestionar pipelines más complejos.

## Requisitos Previos

Antes de comenzar, asegúrate de tener configurado lo siguiente:

### Herramientas necesarias:

- **Google Cloud SDK** instalado y configurado.
- **Terraform** instalado (v1.0 o superior).
- Cuenta de **Google Cloud** con los siguientes servicios habilitados:
  - Google Cloud Functions
  - Google Cloud Storage
  - BigQuery
  - Google Secret Manager

### Configuración de Google Cloud:

Autenticarse en Google Cloud:

```bash
gcloud auth login
gcloud auth application-default login
```

Crear un proyecto de Google Cloud:

```bash
gcloud projects create your-project-id --name="Your Project Name"
```

Seleccionar tu proyecto activo:

```bash
gcloud config set project your-project-id
```

Habilitar las APIs necesarias:

```bash
gcloud services enable cloudfunctions.googleapis.com     bigquery.googleapis.com     storage.googleapis.com     secretmanager.googleapis.com
```

## Instalación y configuración del sistema

### 1. Clonar el repositorio

Clona este repositorio en tu máquina local:

```bash
git clone https://github.com/MauroTravisany/firstlayer_stock_market.git
cd firstlayer_stock_market
```

### 2. Configuración de Google Secret Manager

Crear los secretos en **Google Secret Manager** para almacenar la información sensible como el nombre del bucket, el ID del proyecto, el dataset de BigQuery, etc. Puedes hacer esto desde la consola de Google Cloud o desde la CLI:

```bash
echo "your-bucket-name" > bucket_name.txt
gcloud secrets create bucket_name --data-file=bucket_name.txt

echo "your-project-id" > project_id.txt
gcloud secrets create project_id --data-file=project_id.txt

echo "your-dataset-id" > dataset_id.txt
gcloud secrets create dataset_id --data-file=dataset_id.txt

echo "your-table-id" > table_id.txt
gcloud secrets create table_id --data-file=table_id.txt
```

Otorgar permisos a la cuenta de servicio de **Cloud Functions**:

```bash
gcloud projects add-iam-policy-binding your-project-id     --member="serviceAccount:your-project-id@appspot.gserviceaccount.com"     --role="roles/secretmanager.secretAccessor"
```

### 3. Configuración de Terraform

importante, configurar variables de entorno para **Terraform**:

Antes de ejecutar Terraform, asegúrate de definir las variables necesarias en un archivo `terraform.tfvars` en el directorio `terraform/`:

```hcl
project_id  = "your-project-id"
region      = "us-central1"
bucket_name = "your-bucket-name"
dataset_id  = "your-dataset-id"
table_id    = "your-table-id"
repo_name   = "your-repo-name"
```

Inicializar Terraform:

```bash
cd terraform/
terraform init
```

Aplicar la configuración de Terraform:

```bash
terraform apply -auto-approve
```

### 4. Despliegue de Cloud Functions

Desplegar **Cloud Functions** manualmente (si no lo haces con Terraform):

```bash
gcloud functions deploy function1     --runtime python310     --trigger-http     --source ./cloud-functions/function1     --region us-central1     --entry-point main
```

### 5. Ejecutar localmente (opcional)

Si prefieres hacer pruebas locales antes de desplegar a Google Cloud:

Configurar variables de entorno locales:

En PowerShell:

```powershell
$env:PROJECT_ID="your-project-id"
$env:TICKERS="AAPL,GOOGL,MSFT"
$env:TARGET_DATE="2024-10-10"
```

En cmd:

```cmd
set PROJECT_ID=your-project-id
set TICKERS=AAPL,GOOGL,MSFT
set TARGET_DATE=2024-10-10
```

Ejecutar el código localmente:

```bash
python cloud-functions/daily_stocks/main.py
```

### 6. Automatización del Despliegue (CI/CD)

Puedes integrar **GitHub Actions** o **Google Cloud Build** para automatizar el despliegue continuo (CI/CD). Un ejemplo de configuración de **GitHub Actions** se incluye en el archivo `.github/workflows/deploy.yml` para realizar el despliegue automático de **Cloud Functions** y **Terraform** cada vez que realices un push al repositorio.

## Estructura del repositorio

```bash
/firstlayer_stock_market
│
├── /cloud-functions             # Código de Google Cloud Functions
│   ├── /daily_stocks               # Primer Google Cloud Function
│   │   ├── main.py              # Código Python para la función
│   │   ├── requirements.txt     # Dependencias Python
│   │   └── conf.py              # Configuraciones
│   ├── /function2               # Otra Cloud Function (si es necesaria)
│   └── /tests                   # Pruebas unitarias para las funciones
│
├── /terraform                   # Archivos de configuración de Terraform
│   ├── main.tf                  # Configuración principal de Terraform
│   ├── variables.tf             # Variables de Terraform
│   ├── outputs.tf               # Salidas de Terraform (outputs)
│   └── provider.tf              # Configuración del proveedor de Google Cloud
│
├── README.md                    # Documentación del repositorio
└── .gitignore                   # Ignorar archivos innecesarios (por ejemplo, .env o secrets)
```

## Notas adicionales:

- **Seguridad**: Evita almacenar credenciales directamente en el código o el repositorio. Utiliza **Google Secret Manager** para manejar datos sensibles.
- **Errores comunes**: Asegúrate de haber dado los permisos adecuados a las cuentas de servicio y de haber habilitado todas las APIs necesarias en Google Cloud.

# Stock Portfolio Dashboard

Dashboard Evidence.dev generado desde BigQuery.

## Desarrollo local

Requiere Node.js 18+ y credenciales ADC de Google Cloud:

```powershell
gcloud auth application-default login
$env:BQ_PROJECT_ID = "stocks-437902"
$env:BQ_LOCATION = "us-east1"
cd dashboard
npm install
npm run sources
npm run dev
```

## Build

```powershell
cd dashboard
npm run sources:strict
npm run build:strict
```

El sitio se compila como archivos estaticos. No expone credenciales de BigQuery en el navegador.

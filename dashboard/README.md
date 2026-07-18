# Stock Portfolio Dashboard

Dashboard Evidence.dev generado desde snapshots CSV extraidos de BigQuery durante el build.

## Desarrollo local

Requiere Node.js 18+. Para desarrollo local, primero exporta los CSV desde BigQuery o copia `dashboard/data/` desde un build.

```powershell
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

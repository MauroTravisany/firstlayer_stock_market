# Dataform - Portfolio Valuation

Este proyecto Dataform calcula una clasificacion diaria de la cartera usando:

- precios diarios desde `acciones_dataset.valores_acciones_recientes`
- ratios financieros desde `acciones_dataset.financial_ratios_snapshot`
- ultimos estados financieros desde `acciones_dataset.financial_statements`

## Tabla generada

```text
acciones_dataset.portfolio_valuation_daily
```

La tabla queda particionada por `analysis_date` y clusterizada por `classification, ticker`.

## Clasificaciones

```text
BARATA        valuation_score >= 2
PRECIO_JUSTO valuation_score >= 0 y < 2
CARA          valuation_score < 0
```

Si no hay datos fundamentales suficientes:

```text
SIN_DATOS_FUNDAMENTALES
```

## Estado de datos financieros

```text
FINANCIERO_AYER       snapshot financiero del dia anterior al precio
FINANCIERO_MISMO_DIA  snapshot financiero del mismo dia
FINANCIERO_REZAGADO   snapshot financiero anterior a ayer
SIN_SNAPSHOT_FINANCIERO
```

## Ejecucion local

Desde `dataform/`:

```bash
npm install
npx dataform compile
npx dataform run
```

En GCP Dataform, conectar este directorio como repositorio y programar la ejecucion despues de los ETL diarios.

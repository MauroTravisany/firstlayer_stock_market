---
title: Calidad de datos
---

```sql quality
select
  run_date,
  pipeline,
  ticker,
  data_status,
  severity,
  rows_loaded,
  analysis_impact,
  message
from stocks.data_quality_latest
order by run_date desc, pipeline, ticker
```

```sql quality_summary
select
  pipeline,
  data_status,
  count(*) as registros
from stocks.data_quality_latest
group by pipeline, data_status
order by pipeline, data_status
```

# Calidad de datos

<div style="border-left: 4px solid #ca8a04; background: #fffbeb; padding: 14px 16px; border-radius: 6px; margin: 12px 0 18px;">
  Esta vista controla si los procesos cargaron datos suficientes para confiar en el analisis. Si el impacto es medio o alto, la senal puede ser menos confiable aunque el score se vea atractivo.
</div>

## Resumen por proceso

El grafico muestra cuantos registros quedaron en cada estado por pipeline. Muchos errores en un proceso indican que Yahoo, BigQuery o la fuente de IA no entregaron informacion completa.

<BarChart data={quality_summary} x=pipeline y=registros series=data_status/>

## Detalle de calidad

Tabla de diagnostico por fecha, proceso y ticker. `severity` indica urgencia, `rows_loaded` confirma carga efectiva y `analysis_impact` mide cuanto puede afectar al analisis final.

<DataTable data={quality} rows=50/>

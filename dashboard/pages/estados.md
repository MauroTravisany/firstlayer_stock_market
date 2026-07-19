---
title: Estados
---

```sql status_counts
select
  company_status,
  count(*) as empresas
from stocks.company_status_latest
group by company_status
order by empresas desc
```

```sql current_status
select
  ticker,
  company_status,
  status_group,
  signal,
  sell_signal,
  classification,
  risk_level,
  technical_trend,
  missing_data_impact,
  final_score,
  sell_score,
  round(margin_of_safety_pct * 100, 2) as margen_seguridad_pct,
  last_relevant_change_date,
  last_relevant_change_type,
  days_in_current_status,
  days_since_last_relevant_change
from stocks.company_status_latest
order by status_group, final_score desc, ticker
```

```sql current_status_mobile
select
  ticker,
  company_status as estado,
  classification as valoracion,
  risk_level as riesgo,
  technical_trend as tendencia,
  round(final_score, 1) as score,
  days_in_current_status as dias_estado
from stocks.company_status_latest
order by status_group, final_score desc, ticker
```

```sql recent_changes
select
  analysis_date,
  ticker,
  change_type,
  previous_company_status,
  company_status,
  previous_classification,
  classification,
  previous_risk_level,
  risk_level,
  previous_technical_trend,
  technical_trend,
  final_score_change,
  round(margin_of_safety_change * 100, 2) as cambio_margen_seguridad_pct,
  round(price_change_since_previous_status * 100, 2) as cambio_precio_pct,
  status_reason
from stocks.company_status_changes
order by analysis_date desc, ticker
limit 200
```

# Estados

<div style="border-left: 4px solid #7c3aed; background: #faf5ff; padding: 14px 16px; border-radius: 6px; margin: 12px 0 18px;">
  Esta vista responde si una empresa cambio de estado y cuanto tiempo lleva ahi. Es clave para no reaccionar solo a una alerta diaria aislada.
</div>

## Distribucion actual

El grafico muestra cuantos activos estan en cada estado final. Sirve para ver si el portafolio se esta inclinando hacia compra, espera, sobrevaloracion o riesgo.

<BarChart data={status_counts} x=company_status y=empresas/>

## Estado Actual

Tabla compacta para celular. `dias_estado` indica persistencia: una senal reciente requiere mas cautela que una senal estable por varios dias.

<DataTable data={current_status_mobile} rows=30/>

## Estado detallado

Tabla auditable del estado actual. Incluye senales, valoracion, riesgo, tendencia, impacto de datos faltantes y fechas de cambios relevantes.

<DataTable data={current_status} rows=30/>

## Cambios Relevantes

Historial de cambios de estado. Interpreta `cambio_precio_pct` y `cambio_margen_seguridad_pct` como la magnitud del movimiento que acompano el cambio.

<DataTable data={recent_changes} rows=30/>

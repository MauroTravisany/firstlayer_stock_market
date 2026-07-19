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

<BarChart data={status_counts} x=company_status y=empresas/>

## Estado Actual

<DataTable data={current_status} rows=30/>

## Cambios Relevantes

<DataTable data={recent_changes} rows=30/>

---
title: Reportes IA
---

```sql latest_report
select
  analysis_date,
  summary_type,
  alert_title,
  discord_summary,
  coalesce(full_report, alert_body, dashboard_summary) as reporte_completo,
  alert_sent,
  alert_error,
  created_at
from stocks.portfolio_ai_summary
order by created_at desc
limit 1
```

```sql report_history
select
  analysis_date,
  summary_type,
  alert_title,
  length(discord_summary) as largo_discord,
  length(coalesce(full_report, alert_body, dashboard_summary)) as largo_reporte,
  alert_sent,
  alert_error,
  created_at
from stocks.portfolio_ai_summary
order by created_at desc
limit 20
```

```sql full_reports
select
  analysis_date,
  summary_type,
  alert_title,
  coalesce(full_report, alert_body, dashboard_summary) as reporte_completo
from stocks.portfolio_ai_summary
order by created_at desc
limit 5
```

# Reportes IA

## Ultimo resumen enviado

<DataTable data={latest_report} rows=1/>

## Reportes completos

<DataTable data={full_reports} rows=5/>

## Historial

<DataTable data={report_history} rows=20/>

---
title: Reportes
---

```sql reports
select
  analysis_date,
  summary_type,
  alert_title,
  coalesce(full_report, alert_body, dashboard_summary) as reporte_completo,
  discord_summary,
  alert_sent,
  alert_error,
  created_at
from stocks.portfolio_ai_summary
order by created_at desc
limit 20
```

# Reportes

<DataTable data={reports} rows=20/>

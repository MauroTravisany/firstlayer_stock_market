---
title: Reportes IA
---

```sql latest_report
select
  analysis_date,
  summary_type,
  alert_title,
  discord_summary,
  substr(coalesce(full_report, alert_body, dashboard_summary), 1, 1200) as vista_previa,
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
  substr(discord_summary, 1, 500) as resumen_discord,
  coalesce(full_report, alert_body, dashboard_summary) as reporte_completo
from stocks.portfolio_ai_summary
order by created_at desc
limit 3
```

# Reportes IA

<div style="border-left: 4px solid #2563eb; background: #f8fafc; padding: 14px 16px; border-radius: 6px; margin: 12px 0 18px;">
  Esta pagina guarda los resumenes generados por IA. Discord recibe una version corta para no saturar el canal; aqui queda la version completa para lectura y auditoria.
</div>

## Ultimo resumen enviado

Tabla con el ultimo reporte emitido. `vista_previa` permite revisar rapidamente el contenido, `alert_sent` confirma envio y `alert_error` muestra si Discord rechazo o fallo el mensaje.

<DataTable data={latest_report} rows=1/>

## Reportes completos

Historial reciente con el texto completo disponible en web. Usa esta seccion para leer el contexto que no cabe en Discord: oportunidades, ventas, riesgos y cambios de tendencia.

<DataTable data={full_reports} rows=3/>

## Historial

Registro operativo de los ultimos reportes. Los largos de texto ayudan a verificar que el resumen corto y el reporte completo se generaron correctamente.

<DataTable data={report_history} rows=20/>

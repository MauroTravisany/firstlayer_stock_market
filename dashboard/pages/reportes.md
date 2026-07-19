---
title: Reportes IA
---

```sql weekly_report
with weekly as (
  select
    row_number() over (order by created_at desc) as reporte,
    analysis_date,
    summary_type,
    alert_title,
    discord_summary,
    dashboard_summary,
    top_opportunities,
    overvalued_summary,
    risk_summary,
    coalesce(full_report, alert_body, dashboard_summary) as reporte_completo,
    alert_sent,
    alert_error,
    created_at
  from stocks.portfolio_ai_summary
  where summary_type = 'weekly'
)
select
  analysis_date,
  summary_type,
  alert_title,
  dashboard_summary,
  top_opportunities,
  overvalued_summary,
  risk_summary,
  discord_summary,
  reporte_completo,
  alert_sent,
  alert_error,
  created_at
from weekly
where reporte <= cast(coalesce(nullif('${inputs.reporte_semanal.value}', ''), '1') as integer)
order by reporte desc
limit 1
```

```sql daily_report
select
  analysis_date,
  summary_type,
  alert_title,
  dashboard_summary,
  top_opportunities,
  overvalued_summary,
  risk_summary,
  discord_summary,
  coalesce(full_report, alert_body, dashboard_summary) as reporte_completo,
  alert_sent,
  alert_error,
  created_at
from stocks.portfolio_ai_summary
where summary_type = 'daily'
order by created_at desc
limit 1
```

```sql report_metrics
select
  count(*) as reportes,
  sum(case when summary_type = 'weekly' then 1 else 0 end) as semanales,
  sum(case when summary_type = 'daily' then 1 else 0 end) as diarios,
  max(analysis_date) as ultima_fecha
from stocks.portfolio_ai_summary
```

# Reportes IA

<div style="border-left: 4px solid #2563eb; background: #f8fafc; padding: 14px 16px; border-radius: 6px; margin: 12px 0 18px;">
  Esta pagina guarda los resumenes generados por IA. Discord recibe una version corta para no saturar el canal; aqui queda la version completa para lectura y auditoria.
</div>

<Grid cols=4>
  <Value data={report_metrics} column=reportes title="Reportes"/>
  <Value data={report_metrics} column=semanales title="Semanales"/>
  <Value data={report_metrics} column=diarios title="Diarios"/>
  <Value data={report_metrics} column=ultima_fecha title="Ultima fecha"/>
</Grid>

## Analisis semanal

Selecciona uno de los ultimos analisis semanales. `1` es el mas reciente; los siguientes son semanas anteriores si existen datos cargados.

<Dropdown name=reporte_semanal title="Reporte semanal">
  <DropdownOption value="1" label="Mas reciente"/>
  <DropdownOption value="2" label="Anterior 1"/>
  <DropdownOption value="3" label="Anterior 2"/>
  <DropdownOption value="4" label="Anterior 3"/>
  <DropdownOption value="5" label="Anterior 4"/>
  <DropdownOption value="6" label="Anterior 5"/>
  <DropdownOption value="7" label="Anterior 6"/>
  <DropdownOption value="8" label="Anterior 7"/>
</Dropdown>

<Grid cols=3>
  <Value data={weekly_report} column=analysis_date title="Fecha"/>
  <Value data={weekly_report} column=alert_sent title="Enviado Discord"/>
  <Value data={weekly_report} column=summary_type title="Tipo"/>
</Grid>

<div style="border-left: 4px solid #2563eb; background: #f8fafc; padding: 14px 16px; border-radius: 6px; margin: 12px 0;">
  <h3 style="margin-top: 0;">Resumen ejecutivo semanal</h3>
  <p><Value data={weekly_report} column=dashboard_summary/></p>
</div>

<div style="border-left: 4px solid #0f766e; background: #f0fdfa; padding: 14px 16px; border-radius: 6px; margin: 12px 0;">
  <h3 style="margin-top: 0;">Oportunidades</h3>
  <p><Value data={weekly_report} column=top_opportunities/></p>
</div>

<div style="border-left: 4px solid #dc2626; background: #fef2f2; padding: 14px 16px; border-radius: 6px; margin: 12px 0;">
  <h3 style="margin-top: 0;">Sobrevaloracion y riesgos</h3>
  <p><Value data={weekly_report} column=overvalued_summary/></p>
  <p><Value data={weekly_report} column=risk_summary/></p>
</div>

<div style="border-left: 4px solid #64748b; background: #f8fafc; padding: 14px 16px; border-radius: 6px; margin: 12px 0;">
  <h3 style="margin-top: 0;">Reporte completo</h3>
  <p><Value data={weekly_report} column=reporte_completo/></p>
</div>

## Ultimo analisis diario

Este bloque muestra el ultimo resumen diario como referencia rapida, separado del analisis semanal.

<Grid cols=3>
  <Value data={daily_report} column=analysis_date title="Fecha"/>
  <Value data={daily_report} column=alert_sent title="Enviado Discord"/>
  <Value data={daily_report} column=summary_type title="Tipo"/>
</Grid>

<div style="border-left: 4px solid #2563eb; background: #f8fafc; padding: 14px 16px; border-radius: 6px; margin: 12px 0;">
  <h3 style="margin-top: 0;">Resumen diario</h3>
  <p><Value data={daily_report} column=dashboard_summary/></p>
</div>

<div style="border-left: 4px solid #0f766e; background: #f0fdfa; padding: 14px 16px; border-radius: 6px; margin: 12px 0;">
  <h3 style="margin-top: 0;">Oportunidades del dia</h3>
  <p><Value data={daily_report} column=top_opportunities/></p>
</div>

<div style="border-left: 4px solid #dc2626; background: #fef2f2; padding: 14px 16px; border-radius: 6px; margin: 12px 0;">
  <h3 style="margin-top: 0;">Riesgos del dia</h3>
  <p><Value data={daily_report} column=overvalued_summary/></p>
  <p><Value data={daily_report} column=risk_summary/></p>
</div>

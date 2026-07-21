---
title: Analisis IA
---

```sql ticker_options
select ticker
from stocks.portfolio_latest
order by ticker
```

```sql selected_ai
select
  p.analysis_date,
  p.ticker,
  p.classification,
  p.signal,
  p.sell_signal,
  round(p.final_score, 2) as final_score,
  round(p.sell_score, 2) as sell_score,
  round(p.confidence_score, 2) as confidence_score,
  coalesce(a.ai_summary, p.ai_summary, 'Sin analisis IA reciente para este ticker.') as ai_summary,
  coalesce(a.ai_opportunity, p.ai_opportunity, 'Sin oportunidad IA registrada.') as ai_opportunity,
  coalesce(a.ai_analysis, p.ai_analysis, 'Sin analisis IA reciente para este ticker.') as ai_analysis,
  coalesce(a.ai_fair_value_view, p.ai_fair_value_view, 'Sin lectura IA de valor justo registrada.') as ai_fair_value_view,
  coalesce(a.ai_technical_view, p.ai_technical_view, 'Sin lectura tecnica IA registrada.') as ai_technical_view,
  coalesce(a.ai_risks, p.ai_risks, 'Sin riesgos IA registrados.') as ai_risks,
  coalesce(a.ai_sell_thesis, p.ai_sell_thesis, 'Sin tesis de venta IA registrada.') as ai_sell_thesis,
  coalesce(a.ai_sell_reasons, p.ai_sell_reasons, 'Sin razones de venta IA registradas.') as ai_sell_reasons,
  coalesce(a.ai_sell_price_view, p.ai_sell_price_view, 'Sin lectura IA de precio de venta registrada.') as ai_sell_price_view,
  coalesce(a.ai_decision_support, p.ai_decision_support, 'Sin soporte IA de decision registrado.') as ai_decision_support,
  coalesce(a.ai_sell_decision_support, p.ai_sell_decision_support, 'Sin soporte IA de venta registrado.') as ai_sell_decision_support,
  coalesce(a.data_discrepancies, p.data_discrepancies, 'Sin discrepancias registradas.') as data_discrepancies,
  coalesce(a.external_context_summary, p.external_context_summary, 'Sin contexto externo registrado.') as external_context_summary,
  case when a.ticker is null then 'SIN_IA_RECIENTE' else 'IA_OK' end as estado_ia
from stocks.portfolio_latest p
left join stocks.ai_analysis_latest a using(ticker)
where p.ticker = coalesce(nullif('${inputs.empresa.value}', ''), 'AAPL')
limit 1
```

```sql ai_scores
select
  ticker,
  round(final_score, 1) as score
from stocks.portfolio_latest
order by
  case when signal = 'COMPRAR_OBSERVAR' then 1 when sell_signal = 'VENTA_CLARA' then 2 else 3 end,
  greatest(coalesce(final_score, 0), coalesce(sell_score, 0)) desc,
  ticker
```

```sql daily_summary
select
  analysis_date,
  dashboard_summary,
  top_opportunities,
  overvalued_summary,
  risk_summary,
  alert_sent,
  alert_error
from stocks.portfolio_ai_summary
order by analysis_date desc
limit 1
```

# Analisis IA

## Resumen diario

Este bloque resume el analisis global generado por IA para la fecha mas reciente. `top_opportunities` concentra compras relevantes, `overvalued_summary` muestra riesgos de venta y `alert_sent` confirma si la alerta fue enviada.

<div style="border-left: 4px solid #2563eb; background: #f8fafc; padding: 14px 16px; border-radius: 6px; margin: 12px 0;">
  <h3 style="margin-top: 0;">Resumen del dia</h3>
  <p><Value data={daily_summary} column=dashboard_summary/></p>
</div>

<Grid cols=2>
  <Value data={daily_summary} column=analysis_date title="Fecha"/>
  <Value data={daily_summary} column=alert_sent title="Alerta enviada"/>
</Grid>

<div style="border-left: 4px solid #0f766e; background: #f0fdfa; padding: 14px 16px; border-radius: 6px; margin: 12px 0;">
  <h3 style="margin-top: 0;">Oportunidades principales</h3>
  <p><Value data={daily_summary} column=top_opportunities/></p>
</div>

<div style="border-left: 4px solid #dc2626; background: #fef2f2; padding: 14px 16px; border-radius: 6px; margin: 12px 0;">
  <h3 style="margin-top: 0;">Sobrevaloracion y riesgos</h3>
  <p><Value data={daily_summary} column=overvalued_summary/></p>
  <p><Value data={daily_summary} column=risk_summary/></p>
</div>

## Lector por empresa

Selecciona una empresa para leer la tesis completa sin navegar una tabla ancha. Interpreta `confidence_score` como confianza de la IA sobre la consistencia de datos internos, fuentes externas y senal cuantitativa.

<Dropdown
  name=empresa
  title="Empresa"
  data={ticker_options}
  value=ticker
  defaultValue="AAPL"
/>

<Grid cols=4>
  <Value data={selected_ai} column=ticker title="Ticker"/>
  <Value data={selected_ai} column=signal title="Senal"/>
  <Value data={selected_ai} column=final_score title="Score"/>
  <Value data={selected_ai} column=sell_score title="Score venta"/>
</Grid>

<Grid cols=2>
  <Value data={selected_ai} column=sell_signal title="Senal venta"/>
  <Value data={selected_ai} column=confidence_score title="Confianza"/>
</Grid>

<Grid cols=2>
  <Value data={selected_ai} column=classification title="Clasificacion"/>
  <Value data={selected_ai} column=estado_ia title="Estado IA"/>
</Grid>

<div style="border-left: 4px solid #2563eb; background: #f8fafc; padding: 14px 16px; border-radius: 6px; margin: 12px 0;">
  <h3 style="margin-top: 0;">Resumen ejecutivo</h3>
  <p><Value data={selected_ai} column=ai_summary/></p>
</div>

<div style="border-left: 4px solid #0f766e; background: #f0fdfa; padding: 14px 16px; border-radius: 6px; margin: 12px 0;">
  <h3 style="margin-top: 0;">Oportunidad y valor justo</h3>
  <p><Value data={selected_ai} column=ai_opportunity/></p>
  <p><Value data={selected_ai} column=ai_fair_value_view/></p>
</div>

<div style="border-left: 4px solid #ca8a04; background: #fffbeb; padding: 14px 16px; border-radius: 6px; margin: 12px 0;">
  <h3 style="margin-top: 0;">Riesgos y tecnica</h3>
  <p><Value data={selected_ai} column=ai_risks/></p>
  <p><Value data={selected_ai} column=ai_technical_view/></p>
</div>

<div style="border-left: 4px solid #dc2626; background: #fef2f2; padding: 14px 16px; border-radius: 6px; margin: 12px 0;">
  <h3 style="margin-top: 0;">Venta o sobrevaloracion</h3>
  <p><Value data={selected_ai} column=ai_sell_thesis/></p>
  <p><Value data={selected_ai} column=ai_sell_reasons/></p>
  <p><Value data={selected_ai} column=ai_sell_price_view/></p>
</div>

<div style="border-left: 4px solid #64748b; background: #f8fafc; padding: 14px 16px; border-radius: 6px; margin: 12px 0;">
  <h3 style="margin-top: 0;">Decision y datos externos</h3>
  <p><Value data={selected_ai} column=ai_decision_support/></p>
  <p><Value data={selected_ai} column=ai_sell_decision_support/></p>
  <p><Value data={selected_ai} column=external_context_summary/></p>
  <p><Value data={selected_ai} column=data_discrepancies/></p>
</div>

## Ranking visual

Este grafico permite ubicar rapidamente donde esta cada empresa por score de compra. Para leer el detalle, selecciona el ticker arriba.

<BarChart data={ai_scores} x=ticker y=score/>

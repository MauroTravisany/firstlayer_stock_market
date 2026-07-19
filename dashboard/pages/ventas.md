---
title: Ventas
---

```sql kpis
select
  count(*) as ventas,
  round(avg(sell_score), 2) as score_venta_promedio,
  round(avg(margin_of_safety_pct * 100), 1) as margen_promedio_pct,
  round(avg(confidence_score), 2) as confianza_promedio
from stocks.portfolio_latest
where sell_signal = 'VENTA_CLARA' or signal = 'VENDER_OBSERVAR'
```

```sql ventas
select
  ticker,
  valuation_model,
  primary_metric,
  classification,
  sell_signal,
  signal,
  peer_valuation_label,
  round(sell_score, 2) as sell_score,
  round(final_score, 2) as final_score,
  round(margin_of_safety_pct * 100, 1) as margen_seguridad_pct,
  round(last_close, 2) as precio,
  round(suggested_sell_price, 2) as revisar_sobre,
  round(pe_ratio, 2) as pe_ratio,
  round(forward_pe, 2) as forward_pe,
  round(price_to_sales, 2) as price_to_sales,
  round(price_to_book, 2) as price_to_book,
  round(ev_to_ebitda, 2) as ev_to_ebitda,
  round(adaptive_forward_pe_limit, 2) as limite_forward_pe,
  round(adaptive_price_to_sales_limit, 2) as limite_ps,
  round(adaptive_ev_to_ebitda_limit, 2) as limite_ev_ebitda,
  risk_level,
  technical_trend,
  ai_sell_thesis,
  ai_sell_reasons,
  ai_sell_price_view,
  confidence_score
from stocks.portfolio_latest
where sell_signal = 'VENTA_CLARA' or signal = 'VENDER_OBSERVAR'
order by sell_score desc, confidence_score desc, ticker
limit 5
```

```sql ventas_mobile
select
  ticker,
  round(sell_score, 1) as venta,
  round(final_score, 1) as score,
  round(margin_of_safety_pct * 100, 1) as margen_pct,
  round(last_close, 2) as precio,
  round(suggested_sell_price, 2) as revisar
from stocks.portfolio_latest
where sell_signal = 'VENTA_CLARA' or signal = 'VENDER_OBSERVAR'
order by sell_score desc, confidence_score desc, ticker
limit 5
```

```sql sell_chart
select
  ticker,
  sell_score
from stocks.portfolio_latest
where sell_signal = 'VENTA_CLARA' or signal = 'VENDER_OBSERVAR'
order by sell_score desc, ticker
limit 5
```

# Ventas

<div style="border-left: 4px solid #dc2626; background: #fef2f2; padding: 14px 16px; border-radius: 6px; margin: 12px 0 18px;">
  Esta vista no obliga a vender; identifica empresas donde el precio, multiples, riesgo o deterioro justifican revisar la posicion. El objetivo es separar toma de ganancias, sobrevaloracion y deterioro real.
</div>

<Grid cols=2>
  <Value data={kpis} column=ventas title="Ventas a revisar"/>
  <Value data={kpis} column=score_venta_promedio title="Score venta"/>
  <Value data={kpis} column=margen_promedio_pct title="Margen promedio %"/>
  <Value data={kpis} column=confianza_promedio title="Confianza IA"/>
</Grid>

## Ranking de venta

Grafico de prioridad de salida. Un `sell_score` mas alto significa mayor evidencia de sobrevaloracion, riesgo o perdida de atractivo relativo.

<BarChart data={sell_chart} x=ticker y=sell_score/>

## Vista rapida

Tabla compacta para decidir que revisar primero. `revisar` marca la zona de precio donde la tesis de venta se vuelve mas relevante.

<DataTable data={ventas_mobile} rows=5/>

## Detalle de salida

Tabla completa de venta. Revisa multiples actuales, limites adaptativos, tendencia tecnica, riesgo y tesis de IA para diferenciar una accion cara de una empresa deteriorada.

<DataTable data={ventas} rows=5/>

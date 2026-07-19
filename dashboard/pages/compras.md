---
title: Compras
---

```sql kpis
select
  count(*) as compras,
  round(avg(final_score), 2) as score_promedio,
  round(avg(margin_of_safety_pct * 100), 1) as margen_promedio_pct,
  round(avg(confidence_score), 2) as confianza_promedio
from stocks.portfolio_latest
where signal = 'COMPRAR_OBSERVAR'
```

```sql oportunidades
select
  ticker,
  valuation_model,
  primary_metric,
  peer_valuation_label,
  round(final_score, 2) as final_score,
  round(valuation_score, 2) as valuation_score,
  round(quality_score, 2) as quality_score,
  round(momentum_score, 2) as momentum_score,
  round(technical_score, 2) as technical_score,
  round(risk_score, 2) as risk_score,
  round(margin_of_safety_pct * 100, 1) as margen_seguridad_pct,
  round(last_close, 2) as precio,
  round(suggested_buy_price, 2) as precio_compra_sugerido,
  round(forward_pe, 2) as forward_pe,
  round(price_to_sales, 2) as price_to_sales,
  round(ev_to_ebitda, 2) as ev_to_ebitda,
  round(adaptive_forward_pe_limit, 2) as limite_forward_pe,
  round(adaptive_price_to_sales_limit, 2) as limite_ps,
  round(adaptive_ev_to_ebitda_limit, 2) as limite_ev_ebitda,
  buy_multiple_guardrail_pass,
  ai_summary,
  ai_opportunity,
  ai_risks,
  confidence_score
from stocks.portfolio_latest
where signal = 'COMPRAR_OBSERVAR'
order by final_score desc, confidence_score desc, ticker
limit 5
```

```sql oportunidades_mobile
select
  ticker,
  round(final_score, 1) as score,
  round(margin_of_safety_pct * 100, 1) as margen_pct,
  round(last_close, 2) as precio,
  round(suggested_buy_price, 2) as entrada,
  primary_metric as ratio
from stocks.portfolio_latest
where signal = 'COMPRAR_OBSERVAR'
order by final_score desc, confidence_score desc, ticker
limit 5
```

```sql score_breakdown
select
  ticker,
  final_score,
  valuation_score,
  quality_score,
  momentum_score,
  technical_score,
  risk_score
from stocks.portfolio_latest
where signal = 'COMPRAR_OBSERVAR'
order by final_score desc, ticker
limit 5
```

# Compras

<div style="border-left: 4px solid #0f766e; background: #f0fdfa; padding: 14px 16px; border-radius: 6px; margin: 12px 0 18px;">
  Esta vista muestra solo candidatas con oportunidad clara de compra. La prioridad sube cuando hay descuento frente a pares/industria, buen score de calidad, riesgo controlado y una tesis de IA consistente.
</div>

<Grid cols=2>
  <Value data={kpis} column=compras title="Compras claras"/>
  <Value data={kpis} column=score_promedio title="Score promedio"/>
  <Value data={kpis} column=margen_promedio_pct title="Margen promedio %"/>
  <Value data={kpis} column=confianza_promedio title="Confianza IA"/>
</Grid>

## Ranking de compra

Grafico rapido de conviccion. Mientras mas alto el `final_score`, mas fuerte es la combinacion entre valoracion, calidad, momentum, tecnica y riesgo.

<BarChart data={score_breakdown} x=ticker y=final_score/>

## Vista rapida

Tabla compacta para celular. `margen_pct` es el margen de seguridad estimado y `entrada` es el precio sugerido para que la oportunidad siga siendo atractiva.

<DataTable data={oportunidades_mobile} rows=5/>

## Detalle fundamental

Tabla completa de compra. Compara el precio actual contra limites adaptativos por industria/pares y revisa la explicacion de IA antes de ejecutar.

<DataTable data={oportunidades} rows=5/>

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

<Grid cols=2>
  <Value data={kpis} column=compras title="Compras claras"/>
  <Value data={kpis} column=score_promedio title="Score promedio"/>
  <Value data={kpis} column=margen_promedio_pct title="Margen promedio %"/>
  <Value data={kpis} column=confianza_promedio title="Confianza IA"/>
</Grid>

## Ranking de compra

<BarChart data={score_breakdown} x=ticker y=final_score/>

## Vista rapida

<DataTable data={oportunidades_mobile} rows=5/>

## Detalle fundamental

<DataTable data={oportunidades} rows=5/>

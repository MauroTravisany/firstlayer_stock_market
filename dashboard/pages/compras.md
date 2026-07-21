---
title: Compras
---

```sql kpis
select
  count(*) as compras_observar,
  sum(case when a.ai_final_alert_action = 'ENVIAR_COMPRA' and p.confidence_score >= 0.65 then 1 else 0 end) as compras_claras,
  round(avg(p.final_score), 2) as score_promedio,
  round(avg(p.margin_of_safety_pct * 100), 1) as margen_promedio_pct,
  round(avg(p.confidence_score), 2) as confianza_promedio
from stocks.portfolio_latest p
left join stocks.ai_analysis_latest a using(ticker)
where p.signal = 'COMPRAR_OBSERVAR'
```

```sql oportunidades
select
  p.ticker,
  case
    when a.ai_final_alert_action = 'ENVIAR_COMPRA' and p.confidence_score >= 0.65 then 'COMPRA_CLARA'
    else 'COMPRA_OBSERVAR'
  end as tipo_alerta,
  p.valuation_model,
  p.primary_metric,
  p.peer_valuation_label,
  round(p.final_score, 2) as final_score,
  round(p.valuation_score, 2) as valuation_score,
  round(p.quality_score, 2) as quality_score,
  round(p.momentum_score, 2) as momentum_score,
  round(p.technical_score, 2) as technical_score,
  round(p.risk_score, 2) as risk_score,
  round(p.margin_of_safety_pct * 100, 1) as margen_seguridad_pct,
  round(p.last_close, 2) as precio,
  round(p.suggested_buy_price, 2) as precio_compra_sugerido,
  round(p.forward_pe, 2) as forward_pe,
  round(p.price_to_sales, 2) as price_to_sales,
  round(p.ev_to_ebitda, 2) as ev_to_ebitda,
  round(p.adaptive_forward_pe_limit, 2) as limite_forward_pe,
  round(p.adaptive_price_to_sales_limit, 2) as limite_ps,
  round(p.adaptive_ev_to_ebitda_limit, 2) as limite_ev_ebitda,
  p.buy_multiple_guardrail_pass,
  a.ai_final_alert_action,
  p.ai_summary,
  p.ai_opportunity,
  p.ai_risks,
  p.confidence_score
from stocks.portfolio_latest p
left join stocks.ai_analysis_latest a using(ticker)
where p.signal = 'COMPRAR_OBSERVAR'
order by p.final_score desc, p.confidence_score desc, p.ticker
limit 5
```

```sql oportunidades_mobile
select
  p.ticker,
  case
    when a.ai_final_alert_action = 'ENVIAR_COMPRA' and p.confidence_score >= 0.65 then 'Clara'
    else 'Observar'
  end as tipo,
  round(p.final_score, 1) as score,
  round(p.margin_of_safety_pct * 100, 1) as margen_pct,
  round(p.last_close, 2) as precio,
  round(p.suggested_buy_price, 2) as entrada,
  p.primary_metric as ratio
from stocks.portfolio_latest p
left join stocks.ai_analysis_latest a using(ticker)
where p.signal = 'COMPRAR_OBSERVAR'
order by p.final_score desc, p.confidence_score desc, p.ticker
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
  Esta vista muestra candidatas de compra. `COMPRA_CLARA` cumple umbrales estrictos de IA y confianza; `COMPRA_OBSERVAR` indica que el modelo cuantitativo ve oportunidad, pero requiere validacion por datos, precio o tesis antes de actuar.
</div>

<Grid cols=2>
  <Value data={kpis} column=compras_observar title="Compras a observar"/>
  <Value data={kpis} column=compras_claras title="Compras claras"/>
  <Value data={kpis} column=score_promedio title="Score promedio"/>
  <Value data={kpis} column=margen_promedio_pct title="Margen promedio %"/>
</Grid>

<Grid cols=1>
  <Value data={kpis} column=confianza_promedio title="Confianza IA promedio"/>
</Grid>

## Ranking de compra

Grafico rapido de conviccion. Mientras mas alto el `final_score`, mas fuerte es la combinacion entre valoracion, calidad, momentum, tecnica y riesgo.

<BarChart data={score_breakdown} x=ticker y=final_score/>

## Vista rapida

Tabla compacta para celular. `tipo` separa compra clara de compra a observar; `margen_pct` es el margen de seguridad estimado y `entrada` es el precio sugerido para que la oportunidad siga siendo atractiva.

<DataTable data={oportunidades_mobile} rows=5/>

## Detalle fundamental

Tabla completa de compra. `tipo_alerta` explica si la oportunidad ya es clara o solo observacion. Compara el precio actual contra limites adaptativos por industria/pares y revisa la explicacion de IA antes de ejecutar.

<DataTable data={oportunidades} rows=5/>

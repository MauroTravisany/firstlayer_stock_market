---
title: Panel de cartera
---

```sql latest_date
select max(analysis_date) as analysis_date
from stocks.portfolio_latest
```

```sql kpis
select
  count(*) as activos,
  sum(case when asset_type = 'STOCK' then 1 else 0 end) as acciones,
  sum(case when asset_type = 'ETF' then 1 else 0 end) as etfs,
  round(avg(final_score), 2) as score_promedio,
  sum(case when signal = 'COMPRAR_OBSERVAR' then 1 else 0 end) as compras,
  sum(case when sell_signal = 'VENTA_CLARA' or signal = 'VENDER_OBSERVAR' then 1 else 0 end) as ventas,
  sum(case when risk_level = 'ALTO' then 1 else 0 end) as riesgo_alto,
  sum(case when missing_data_impact in ('ALTO', 'MEDIO') then 1 else 0 end) as datos_observar
from stocks.portfolio_latest
```

```sql signal_mix
select
  signal,
  count(*) as activos
from stocks.portfolio_latest
group by signal
order by activos desc
```

```sql status_mix
select
  company_status,
  count(*) as activos
from stocks.company_status_latest
group by company_status
order by activos desc
```

```sql top_actions
select
  ticker,
  case
    when signal = 'COMPRAR_OBSERVAR' then 'Compra'
    when sell_signal = 'VENTA_CLARA' or signal = 'VENDER_OBSERVAR' then 'Venta'
    when signal = 'SOBREVALORADA' then 'Sobrevalorada'
    when risk_level = 'ALTO' then 'Riesgo'
    else 'Seguimiento'
  end as accion,
  signal,
  sell_signal,
  classification,
  valuation_model,
  primary_metric,
  round(final_score, 2) as final_score,
  round(sell_score, 2) as sell_score,
  round(margin_of_safety_pct * 100, 1) as margen_seguridad_pct,
  round(last_close, 2) as precio,
  round(suggested_buy_price, 2) as compra_sugerida,
  round(suggested_sell_price, 2) as venta_sugerida,
  peer_valuation_label,
  risk_level,
  technical_trend
from stocks.portfolio_latest
where signal = 'COMPRAR_OBSERVAR'
   or sell_signal = 'VENTA_CLARA'
   or signal in ('VENDER_OBSERVAR', 'SOBREVALORADA', 'RIESGO_ALTO')
order by
  case
    when signal = 'COMPRAR_OBSERVAR' then 1
    when sell_signal = 'VENTA_CLARA' or signal = 'VENDER_OBSERVAR' then 2
    else 3
  end,
  greatest(coalesce(final_score, 0), coalesce(sell_score, 0)) desc,
  ticker
limit 12
```

```sql buy_list
select
  ticker,
  valuation_model,
  primary_metric,
  round(final_score, 2) as score,
  round(margin_of_safety_pct * 100, 1) as margen_pct,
  round(last_close, 2) as precio,
  round(suggested_buy_price, 2) as entrada,
  round(adaptive_price_to_sales_limit, 2) as limite_ps,
  round(adaptive_forward_pe_limit, 2) as limite_fpe,
  ai_summary
from stocks.portfolio_latest
where signal = 'COMPRAR_OBSERVAR'
order by final_score desc, ticker
limit 5
```

```sql sell_list
select
  ticker,
  valuation_model,
  primary_metric,
  round(sell_score, 2) as score_venta,
  round(final_score, 2) as score,
  round(margin_of_safety_pct * 100, 1) as margen_pct,
  round(last_close, 2) as precio,
  round(suggested_sell_price, 2) as revisar_sobre,
  ai_sell_thesis
from stocks.portfolio_latest
where sell_signal = 'VENTA_CLARA' or signal = 'VENDER_OBSERVAR'
order by sell_score desc, ticker
limit 5
```

```sql model_distribution
select
  valuation_model,
  count(*) as activos,
  round(avg(final_score), 2) as score_promedio
from stocks.portfolio_latest
group by valuation_model
order by activos desc, valuation_model
```

```sql ranking
select
  ticker,
  asset_type,
  signal,
  sell_signal,
  classification,
  valuation_model,
  primary_metric,
  buy_multiple_guardrail_pass,
  round(final_score, 2) as final_score,
  round(sell_score, 2) as sell_score,
  round(margin_of_safety_pct * 100, 1) as margen_seguridad_pct,
  round(last_close, 2) as precio,
  round(forward_pe, 2) as forward_pe,
  round(price_to_sales, 2) as price_to_sales,
  round(price_to_book, 2) as price_to_book,
  round(ev_to_ebitda, 2) as ev_to_ebitda,
  peer_valuation_label,
  risk_level,
  technical_trend,
  missing_data_impact
from stocks.portfolio_latest
order by
  case when signal = 'COMPRAR_OBSERVAR' then 1 when sell_signal = 'VENTA_CLARA' or signal = 'VENDER_OBSERVAR' then 2 else 3 end,
  final_score desc,
  ticker
```

# Panel de cartera

Fecha procesada: <Value data={latest_date} column=analysis_date/>

<Grid cols=4>
  <Value data={kpis} column=activos title="Activos"/>
  <Value data={kpis} column=acciones title="Acciones"/>
  <Value data={kpis} column=compras title="Compras claras"/>
  <Value data={kpis} column=ventas title="Ventas a revisar"/>
</Grid>

<Grid cols=4>
  <Value data={kpis} column=score_promedio title="Score promedio"/>
  <Value data={kpis} column=etfs title="ETFs"/>
  <Value data={kpis} column=riesgo_alto title="Riesgo alto"/>
  <Value data={kpis} column=datos_observar title="Datos a revisar"/>
</Grid>

## Acciones prioritarias

<DataTable data={top_actions} rows=12/>

## Compras claras

<DataTable data={buy_list} rows=5/>

## Ventas a revisar

<DataTable data={sell_list} rows=5/>

## Distribucion de estados

<Grid cols=2>
  <BarChart data={signal_mix} x=signal y=activos/>
  <BarChart data={status_mix} x=company_status y=activos/>
</Grid>

## Modelos de valoracion

<DataTable data={model_distribution} rows=20/>

## Ranking auditable

<DataTable data={ranking} rows=30/>

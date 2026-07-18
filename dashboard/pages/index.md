---
title: Cartera diaria
---

```sql latest_date
select max(analysis_date) as analysis_date
from stocks.portfolio_latest
```

```sql kpis
select
  count(*) as empresas,
  round(avg(final_score), 2) as score_promedio,
  sum(case when signal = 'COMPRAR_OBSERVAR' then 1 else 0 end) as compras_observar,
  sum(case when sell_signal = 'VENTA_CLARA' or signal = 'VENDER_OBSERVAR' then 1 else 0 end) as ventas_observar
from stocks.portfolio_latest
```

```sql signal_mix
select
  signal,
  count(*) as empresas
from stocks.portfolio_latest
group by signal
order by empresas desc
```

```sql top_buy
select
  ticker,
  final_score,
  valuation_score,
  quality_score,
  momentum_score,
  risk_score,
  signal,
  ai_summary
from stocks.portfolio_latest
where signal = 'COMPRAR_OBSERVAR'
order by final_score desc, ticker
limit 5
```

```sql top_sell
select
  ticker,
  sell_score,
  suggested_sell_price,
  last_close,
  sell_signal,
  signal,
  ai_sell_thesis
from stocks.portfolio_latest
where sell_signal = 'VENTA_CLARA' or signal = 'VENDER_OBSERVAR'
order by sell_score desc, ticker
limit 5
```

```sql ranking
select
  ticker,
  signal,
  sell_signal,
  classification,
  final_score,
  sell_score,
  last_close,
  return_5d,
  return_20d,
  pe_ratio,
  forward_pe,
  price_to_sales,
  roe,
  debt_to_equity
from stocks.portfolio_latest
order by final_score desc, ticker
```

# Cartera diaria

Ultima fecha procesada: <Value data={latest_date} column=analysis_date/>

<Grid cols=4>
  <Value data={kpis} column=empresas title="Empresas"/>
  <Value data={kpis} column=score_promedio title="Score promedio"/>
  <Value data={kpis} column=compras_observar title="Compras a observar"/>
  <Value data={kpis} column=ventas_observar title="Ventas a observar"/>
</Grid>

## Distribucion de senales

<BarChart data={signal_mix} x=signal y=empresas/>

## Top 5 oportunidades de compra

<DataTable data={top_buy} rows=5/>

## Top 5 alertas de venta

<DataTable data={top_sell} rows=5/>

## Ranking completo

<DataTable data={ranking} rows=30/>

---
title: Alertas de venta
---

```sql ventas
select
  ticker,
  sell_score,
  sell_signal,
  final_score,
  last_close,
  suggested_sell_price,
  pe_ratio,
  forward_pe,
  price_to_sales,
  ev_to_ebitda,
  roe,
  ai_sell_thesis,
  ai_sell_reasons,
  ai_sell_price_view,
  confidence_score
from stocks.portfolio_latest
where sell_signal = 'VENTA_CLARA' or signal = 'VENDER_OBSERVAR'
order by sell_score desc, confidence_score desc, ticker
limit 5
```

# Alertas de venta

Top 5 acciones con senal de venta o revision por sobrevaloracion, ordenadas de mayor a menor score de venta.

<BarChart data={ventas} x=ticker y=sell_score/>

<DataTable data={ventas} rows=5/>

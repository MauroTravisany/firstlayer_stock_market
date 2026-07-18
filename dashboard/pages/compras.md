---
title: Oportunidades de compra
---

```sql oportunidades
select
  ticker,
  final_score,
  valuation_score,
  quality_score,
  momentum_score,
  risk_score,
  last_close,
  pe_ratio,
  forward_pe,
  price_to_sales,
  roe,
  ai_summary,
  ai_opportunity,
  ai_risks,
  confidence_score
from stocks.portfolio_latest
where signal = 'COMPRAR_OBSERVAR'
order by final_score desc, confidence_score desc, ticker
limit 5
```

# Oportunidades de compra

Top 5 acciones con senal clara de compra, ordenadas de mejor a menor score.

<BarChart data={oportunidades} x=ticker y=final_score/>

<DataTable data={oportunidades} rows=5/>

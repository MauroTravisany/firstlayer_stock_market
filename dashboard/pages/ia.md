---
title: Analisis IA
---

```sql ai_rows
select
  analysis_date,
  ticker,
  signal,
  sell_signal,
  final_score,
  sell_score,
  confidence_score,
  ai_summary,
  ai_analysis,
  ai_opportunity,
  ai_risks,
  ai_sell_thesis,
  ai_sell_reasons,
  data_discrepancies,
  external_context_summary
from stocks.ai_analysis_latest
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

<DataTable data={daily_summary} rows=1/>

## Detalle por accion

<DataTable data={ai_rows} rows=30/>

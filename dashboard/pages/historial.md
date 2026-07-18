---
title: Historial
---

```sql score_history
select
  analysis_date,
  ticker,
  final_score,
  last_close,
  signal
from stocks.portfolio_history
where analysis_date >= current_date - interval '90 days'
order by analysis_date, ticker
```

```sql changes
select
  analysis_date,
  ticker,
  previous_signal,
  signal,
  final_score,
  final_score_change,
  last_close
from stocks.portfolio_history
where signal_changed = true
order by analysis_date desc, ticker
limit 100
```

# Historial

<LineChart data={score_history} x=analysis_date y=final_score series=ticker/>

## Cambios recientes de senal

<DataTable data={changes} rows=25/>

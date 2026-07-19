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

<div style="border-left: 4px solid #2563eb; background: #f8fafc; padding: 14px 16px; border-radius: 6px; margin: 12px 0 18px;">
  Esta vista muestra la evolucion de las senales. Es util para distinguir cambios persistentes de movimientos puntuales.
</div>

## Evolucion de score

El grafico muestra el `final_score` por empresa durante los ultimos 90 dias. Una tendencia creciente mejora la calidad de una oportunidad; una caida persistente reduce conviccion.

<LineChart data={score_history} x=analysis_date y=final_score series=ticker/>

## Cambios recientes de senal

Tabla de eventos donde una empresa cambio de senal. `final_score_change` ayuda a medir si el cambio fue marginal o material.

<DataTable data={changes} rows=25/>

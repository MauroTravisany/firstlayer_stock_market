---
title: Backtesting
---

```sql summary
select
  signal,
  backtest_status,
  count(*) as senales,
  round(avg(forward_return_20d) * 100, 2) as retorno_20d_promedio,
  round(avg(forward_return_60d) * 100, 2) as retorno_60d_promedio,
  round(avg(case when signal_success_60d then 1 else 0 end) * 100, 2) as tasa_acierto_60d
from stocks.portfolio_signal_backtest
where backtest_status != 'PENDIENTE_DATOS_FUTUROS'
group by signal, backtest_status
order by senales desc
```

```sql latest
select
  analysis_date,
  ticker,
  signal,
  sell_signal,
  classification,
  final_score,
  sell_score,
  round(margin_of_safety_pct * 100, 2) as margen_seguridad_pct,
  risk_level,
  technical_trend,
  round(forward_return_20d * 100, 2) as retorno_20d_pct,
  round(forward_return_60d * 100, 2) as retorno_60d_pct,
  backtest_status
from stocks.portfolio_signal_backtest
order by analysis_date desc, ticker
limit 300
```

# Backtesting

<div style="border-left: 4px solid #334155; background: #f8fafc; padding: 14px 16px; border-radius: 6px; margin: 12px 0 18px;">
  Esta vista valida historicamente si las senales funcionaron despues de emitirse. No predice el futuro, pero ayuda a ajustar reglas si una senal falla de forma repetida.
</div>

## Resumen de efectividad

Tabla agregada por senal y estado de backtest. `retorno_20d_promedio`, `retorno_60d_promedio` y `tasa_acierto_60d` muestran si la senal agrego valor despues de 20 y 60 dias.

<DataTable data={summary} rows=20/>

## Detalle

Tabla de cada senal historica con retornos futuros conocidos. Si `backtest_status` esta pendiente, aun no existe suficiente tiempo posterior para evaluar esa senal.

<DataTable data={latest} rows=25/>

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
  sum(case when asset_type = 'CRYPTO' then 1 else 0 end) as cripto,
  round(avg(final_score), 2) as score_promedio,
  sum(case when signal = 'COMPRAR_OBSERVAR' then 1 else 0 end) as compras_observar,
  sum(case when signal = 'CRYPTO_ACUMULAR_OBSERVAR' then 1 else 0 end) as cripto_acumular,
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
    when signal = 'CRYPTO_ACUMULAR_OBSERVAR' then 'Cripto acumular'
    when signal = 'CRYPTO_SOBREEXTENDIDO' then 'Cripto extendida'
    when signal = 'CRYPTO_RIESGO_ALTO' then 'Cripto riesgo'
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
   or signal in ('CRYPTO_ACUMULAR_OBSERVAR', 'CRYPTO_SOBREEXTENDIDO', 'CRYPTO_RIESGO_ALTO')
   or sell_signal = 'VENTA_CLARA'
   or signal in ('VENDER_OBSERVAR', 'SOBREVALORADA', 'RIESGO_ALTO')
order by
  case
    when signal = 'COMPRAR_OBSERVAR' then 1
    when signal = 'CRYPTO_ACUMULAR_OBSERVAR' then 2
    when sell_signal = 'VENTA_CLARA' or signal = 'VENDER_OBSERVAR' then 3
    when signal in ('CRYPTO_SOBREEXTENDIDO', 'CRYPTO_RIESGO_ALTO') then 4
    else 3
  end,
  greatest(coalesce(final_score, 0), coalesce(sell_score, 0)) desc,
  ticker
limit 12
```

```sql mobile_actions
select
  ticker,
  case
    when signal = 'COMPRAR_OBSERVAR' then 'Compra'
    when signal = 'CRYPTO_ACUMULAR_OBSERVAR' then 'Cripto'
    when signal = 'CRYPTO_SOBREEXTENDIDO' then 'Extendida'
    when signal = 'CRYPTO_RIESGO_ALTO' then 'Riesgo cripto'
    when sell_signal = 'VENTA_CLARA' or signal = 'VENDER_OBSERVAR' then 'Venta'
    when signal = 'SOBREVALORADA' then 'Cara'
    when risk_level = 'ALTO' then 'Riesgo'
    else 'Seguir'
  end as accion,
  round(final_score, 1) as score,
  round(sell_score, 1) as venta,
  round(margin_of_safety_pct * 100, 1) as margen_pct,
  round(last_close, 2) as precio
from stocks.portfolio_latest
where signal = 'COMPRAR_OBSERVAR'
   or signal in ('CRYPTO_ACUMULAR_OBSERVAR', 'CRYPTO_SOBREEXTENDIDO', 'CRYPTO_RIESGO_ALTO')
   or sell_signal = 'VENTA_CLARA'
   or signal in ('VENDER_OBSERVAR', 'SOBREVALORADA', 'RIESGO_ALTO')
order by
  case
    when signal = 'COMPRAR_OBSERVAR' then 1
    when signal = 'CRYPTO_ACUMULAR_OBSERVAR' then 2
    when sell_signal = 'VENTA_CLARA' or signal = 'VENDER_OBSERVAR' then 3
    when signal in ('CRYPTO_SOBREEXTENDIDO', 'CRYPTO_RIESGO_ALTO') then 4
    else 3
  end,
  greatest(coalesce(final_score, 0), coalesce(sell_score, 0)) desc,
  ticker
limit 10
```

```sql buy_list
select
  p.ticker,
  case
    when a.ai_final_alert_action = 'ENVIAR_COMPRA' and p.confidence_score >= 0.65 then 'COMPRA_CLARA'
    else 'COMPRA_OBSERVAR'
  end as tipo_alerta,
  p.valuation_model,
  p.primary_metric,
  round(p.final_score, 2) as score,
  round(p.margin_of_safety_pct * 100, 1) as margen_pct,
  round(p.last_close, 2) as precio,
  round(p.suggested_buy_price, 2) as entrada,
  round(p.adaptive_price_to_sales_limit, 2) as limite_ps,
  round(p.adaptive_forward_pe_limit, 2) as limite_fpe,
  p.ai_summary
from stocks.portfolio_latest p
left join stocks.ai_analysis_latest a using(ticker)
where p.signal = 'COMPRAR_OBSERVAR'
order by p.final_score desc, p.ticker
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

<div style="border-left: 4px solid #2563eb; background: #f8fafc; padding: 14px 16px; border-radius: 6px; margin: 12px 0 18px;">
  Vista ejecutiva del portafolio. Los scores combinan valoracion, calidad, momentum, tendencia tecnica, riesgo y validacion por IA. Una compra clara no significa comprar automaticamente: significa que el activo merece revision prioritaria con los datos disponibles.
</div>

<Grid cols=2>
  <Value data={kpis} column=activos title="Activos"/>
  <Value data={kpis} column=acciones title="Acciones"/>
  <Value data={kpis} column=compras_observar title="Compras a observar"/>
  <Value data={kpis} column=ventas title="Ventas a revisar"/>
</Grid>

<Grid cols=2>
  <Value data={kpis} column=score_promedio title="Score promedio"/>
  <Value data={kpis} column=etfs title="ETFs"/>
  <Value data={kpis} column=cripto title="Cripto"/>
  <Value data={kpis} column=riesgo_alto title="Riesgo alto"/>
  <Value data={kpis} column=cripto_acumular title="Cripto acumular"/>
</Grid>

## Acciones prioritarias

Resumen movil de las empresas que requieren atencion primero. `score` prioriza compra, `venta` prioriza salida/revision y `margen_pct` muestra que tan lejos esta el precio respecto al valor de referencia calculado.

<DataTable data={mobile_actions} rows=10/>

## Detalle prioritario

Tabla de auditoria para entender por que una empresa aparece como compra, venta, cara o riesgo. Revisa `valuation_model`, `primary_metric`, precios sugeridos, riesgo y tendencia antes de tomar una decision.

<DataTable data={top_actions} rows=12/>

## Compras a observar

Muestra maximo 5 oportunidades de compra ordenadas por score. `tipo_alerta` separa compra clara de compra a observar; `entrada` es el precio sugerido de compra y los limites adaptativos indican contra que multiples se esta comparando segun industria y pares.

<DataTable data={buy_list} rows=5/>

## Ventas a revisar

Muestra maximo 5 empresas con posible sobrevaloracion o deterioro. `revisar_sobre` es el precio/zona desde donde el sistema considera mas fuerte la tesis de venta.

<DataTable data={sell_list} rows=5/>

## Distribucion de estados

Estos graficos indican como esta repartido el portafolio por senal operativa y por estado final de empresa. Si aumenta la concentracion en riesgo, venta o datos a revisar, conviene mirar calidad de datos e historial.

<BarChart data={signal_mix} x=signal y=activos/>

<BarChart data={status_mix} x=company_status y=activos/>

## Modelos de valoracion

Indica que modelo domina en cada activo. Sirve para validar que una empresa se este evaluando con una metodologia coherente con su naturaleza: crecimiento, calidad defensiva, ETF, cyclical, etc.

<DataTable data={model_distribution} rows=20/>

## Ranking auditable

Tabla completa para trazabilidad diaria. Usa `final_score`, `sell_score`, multiples, comparacion contra pares, tendencia tecnica y datos faltantes para explicar el estado final de cada empresa.

<DataTable data={ranking} rows=30/>

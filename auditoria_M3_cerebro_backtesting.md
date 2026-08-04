# Auditoria M3 - Cerebro de optimizacion de backtesting

Fecha: 2026-08-04  
Alcance: V1-V4, simulacion historica y candidatos de ponderaciones. No modifica reglas productivas ni cuentas reales.

## Principio operativo

El cerebro solo propone parametros para una corrida de backtesting identificable (`run_id`). Cada propuesta conserva:

- formula y valores de entrada;
- periodo de entrenamiento y de validacion fuera de muestra;
- costos de operacion netos de spread y slippage;
- cobertura de fuentes y brechas conocidas;
- metricas por estrategia V1-V4;
- veredicto mecanico y una interpretacion de IA en espanol.

No se permite promover un peso al proceso diario desde este componente. Un candidato solo puede quedar como `BACKTEST_ONLY`, `PROPOSED`, `REJECTED` o `INSUFFICIENT_DATA`.

## Iteracion controlada

La primera generacion explora alrededor del baseline. Cada generacion posterior toma los tres candidatos auditados con mejor evidencia de validacion y crea una exploracion local alrededor de ellos. El orden de seleccion prioriza profit factor, retorno neto despues de costos, cola de perdidas, tasa de acierto y PnL neto.

Cada candidato conserva `generation`, `parent_run_id` y `parent_candidate_id`. Esto permite reconstruir por que un peso fue probado y evita que la IA modifique parametros sin evidencia cuantitativa.

El ciclo tiene un limite de seis generaciones. Se considera una mejora material solo si el mejor candidato de la nueva generacion mejora en al menos 2 puntos el puntaje ajustado por riesgo, sin empeorar el drawdown maximo en mas de 0.25 puntos porcentuales. Dos generaciones seguidas sin mejora material cierran la busqueda: agregar mas combinaciones en ese punto seria sobreajuste, no aprendizaje.

## Capital y decision de promocion

Cada candidato se evalua como cuatro carteras independientes: una para V1, una para V2, una para V3 y una para V4. Cada una inicia con **CLP 10.000.000**, mantiene solo una posicion a la vez y usa el notional definido por el candidato, acotado por el capital disponible. Por eso los resultados de V1-V4 nunca se suman.

La comparacion de generaciones usa capital final neto de costos, retorno final, profit factor, drawdown maximo, p05 de perdida y tasa de acierto. Para siquiera recomendar paper trading, el candidato debe cubrir V1-V4, tener al menos 80 cierres totales, retorno promedio positivo, profit factor >= 1.10, drawdown maximo <= 12% y p05 mejor que -CLP 250.000.

La convergencia no activa produccion automaticamente. El unico resultado posible del cerebro es `REQUIERE_VALIDACION_PAPER_Y_APROBACION_EXPLICITA`; las variantes `brain_*` estan bloqueadas del motor diario. Una promocion posterior requiere una aprobacion explicita y evidencia adicional de paper trading fuera del backtest.

## Formula evaluada

Para cada trade, la capa contextual ya parte del `setup_score` de V1-V4. El candidato ajusta el filtro y el tamano teorico, sin reescribir retroactivamente la senal base:

```text
contextual_setup_score = setup_score
  + fear_weight * fear_component
  + monetary_weight * monetary_component
  + earnings_weight * earnings_component
  + company_lifecycle_weight * lifecycle_component
  + quality_weight * quality_component
  + valuation_state_weight * valuation_component
  + political_risk_weight * political_component
  + crypto_cycle_weight * crypto_component

trade = contextual_setup_score >= min_trade_score + min_trade_score_add
position_notional = base_position_notional * position_size_multiplier

net_return = gross_return - estimated_roundtrip_cost_pct / 100
net_pnl = position_notional * net_return
```

`estimated_roundtrip_cost_pct` incluye costo de ida y vuelta: spread estimado y slippage estimado. Ningun ranking usa PnL bruto como objetivo.

## Objetivo y protecciones

El puntaje de seleccion se calcula solo con validacion fuera de muestra:

```text
objective = 0.35 * normalized_net_pnl
          + 0.25 * capped_profit_factor
          + 0.20 * win_rate
          - 0.15 * normalized_max_drawdown
          - 0.05 * tail_loss_penalty
```

Un candidato requiere, como minimo, PnL neto positivo, profit factor >= 1.10, muestra suficiente, drawdown no peor que el control dentro de tolerancia y validacion de calidad de datos aprobada. De lo contrario se rechaza aunque su retorno bruto parezca atractivo.

## Limitaciones conocidas a registrar en cada corrida

1. Precios diarios: cobertura larga desde 2019; no debe confundirse con datos intradia.
2. Earnings y noticias: cobertura historica corta; no se usan para demostrar causalidad desde 2019.
3. Tasas, politica y miedo: se guardan como proxies si faltan fuentes historicas verificables.
4. Cada `max_holding_days` se mide desde ahora en sesiones observables, no en dias calendario. Esto corrige el hallazgo M2-H1.
5. La optimizacion busca robustez, no una promesa de rentabilidad ni sobreajuste al pasado.

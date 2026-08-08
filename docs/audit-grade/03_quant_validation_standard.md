# 03 — Estándar de validación cuantitativa

## 1. Propósito

Este estándar define cuándo un resultado histórico puede considerarse evidencia y cuándo solo es exploración. Aplica a V1–V4, variantes contextuales, Strategy Brain y futuras fórmulas por activo.

La pregunta principal no es “¿ganó dinero en el pasado?”, sino:

> ¿Existe evidencia estable, fuera de muestra, después de costos y frente a benchmarks, de que la regla mejora una alternativa más simple sin depender de un periodo, activo o parámetro específico?

## 2. Clases de resultado

```text
EXPLORATORY
VALIDATION_CANDIDATE
OUT_OF_SAMPLE_SUPPORTED
SHADOW_SUPPORTED
PAPER_SUPPORTED
REJECTED
INSUFFICIENT_EVIDENCE
INVALID_DATA_OR_METHOD
```

Solo `PAPER_SUPPORTED` puede ser considerado para un gate posterior. Ningún resultado histórico llega directamente a ejecución.

## 3. Protocolo pre-registrado

Antes de cada experimento se registra:

- hipótesis económica/técnica;
- universo y versión;
- features permitidas;
- fórmula y rango de parámetros;
- ventanas temporales;
- modelo de costos y ejecución;
- benchmarks;
- métricas primarias y secundarias;
- criterio de rechazo;
- número máximo de hipótesis/candidatos;
- random seed;
- regla de parada;
- qué conjunto queda bloqueado como test.

Modificar estas decisiones después de observar el test invalida el test y obliga a crear otro experimento.

## 4. Particiones temporales

### 4.1 Prohibición

No reutilizar la misma ventana como `validation` durante múltiples generaciones adaptativas y luego presentarla como evidencia final.

### 4.2 Nested walk-forward

Diseño mínimo recomendado:

```text
Outer fold 1
  Inner train:      2019-2021
  Inner validation: 2022
  Outer test:       2023

Outer fold 2
  Inner train:      2019-2022
  Inner validation: 2023
  Outer test:       2024

Outer fold 3
  Inner train:      2019-2023
  Inner validation: 2024
  Outer test:       2025

Final locked test
  Train/tune:       hasta 2025
  Test final:       2026 o periodo posterior no observado
```

Las fechas reales deben ajustarse a cobertura, pero la estructura es obligatoria.

### 4.3 Purging y embargo

Si una operación puede durar `H` sesiones:

- eliminar de train observaciones cuyas etiquetas se solapen con validation/test;
- aplicar embargo de al menos `H` sesiones entre folds cuando corresponda;
- registrar el número de observaciones purgadas.

## 5. Unidad experimental

Cada combinación de:

```text
universe_version
feature_set_version
strategy_version
parameter_set
execution_model_version
cost_model_version
train/validation/test windows
```

es una hipótesis independiente y cuenta en el presupuesto de múltiples pruebas.

## 6. Benchmarks obligatorios

Cada estrategia se compara, cuando sea aplicable, contra:

1. cash/risk-free proxy;
2. SPY buy-and-hold total return;
3. QQQ para estrategias growth/tech;
4. buy-and-hold del mismo universo con pesos definidos;
5. baseline V1 o regla simple pre-registrada;
6. estrategia aleatoria o permutada con exposición/holding comparables;
7. benchmark específico del activo para cripto o sector.

No basta con capital final mayor al inicial.

## 7. Modelo de cartera

Cada reporte declara uno de estos modelos:

### `FIXED_NOTIONAL_EXPERIMENT`

- el notional no depende de equity;
- sirve para medir señal/expectancy;
- no se interpreta como CAGR de cartera autofinanciada.

### `SELF_FINANCING_PORTFOLIO`

- el capital disponible limita el notional;
- sizing usa equity previa;
- comisiones, slippage y cash se contabilizan;
- permite métricas de cartera como CAGR.

No mezclar métricas de ambos modelos.

## 8. Modelo de ejecución

### 8.1 Entradas

- señales diarias entran en la siguiente apertura observable;
- aplicar spread/slippage al lado correcto;
- rechazar entrada si falta la sesión o el precio;
- registrar orden no ejecutada cuando aplica límite/gap/liquidez.

### 8.2 Stops y gaps

Para long:

```text
if open <= stop:
    fill = open ajustado por slippage adverso
elif low <= stop:
    fill = stop ajustado por slippage
```

Para short simulado, regla simétrica.

### 8.3 Stop y target en la misma vela

- con datos diarios, usar convención conservadora pre-registrada;
- reportar cuántos trades fueron ambiguos;
- ejecutar análisis de sensibilidad con stop-first y target-first;
- no ocultar la diferencia.

### 8.4 Time exits

- horizonte contado en sesiones observables, no días calendario;
- calendario por exchange/activo;
- cripto 24/7 tratado por separado.

### 8.5 Liquidez y capacidad

Cuando haya datos suficientes:

- limitar participación en volumen;
- modelar slippage por ADV/volatilidad;
- excluir barras con calidad insuficiente;
- reportar capacidad estimada.

## 9. Costos

El modelo de costos incluye y versiona:

- spread;
- slippage;
- comisiones;
- FX USD/CLP histórico cuando el reporte está en CLP;
- costos de borrow solo para shorts reales futuros;
- fees específicos de cripto;
- impacto de mercado/capacidad cuando aplique.

Se ejecutan escenarios:

```text
BASE_COST
STRESS_1_5X
STRESS_2X
```

Una estrategia no es robusta si desaparece con un estrés razonable.

## 10. Métricas mínimas

### Retorno y riesgo

- retorno neto total;
- CAGR solo para cartera autofinanciada;
- volatilidad anualizada;
- Sharpe con risk-free declarado;
- Sortino;
- Calmar;
- max drawdown y duración;
- Ulcer index;
- VaR/CVaR o Expected Shortfall;
- peor día/semana/mes.

### Trades

- número de señales y fills;
- win rate;
- ganancia/pérdida media y mediana;
- payoff ratio;
- profit factor;
- expectancy neta;
- MAE/MFE;
- holding medio;
- turnover;
- exposición temporal;
- P05/P01 de PnL.

### Comparación

- alpha/beta frente a benchmark cuando sea significativo;
- information ratio;
- tracking error;
- retorno incremental sobre baseline;
- drawdown incremental;
- hit rate por fold/año/régimen.

## 11. Incertidumbre

No usar únicamente thresholds puntuales.

Reportar:

- intervalos bootstrap block-aware de retorno, expectancy y drawdown;
- intervalo de win rate;
- probabilidad posterior de expectancy > 0;
- estabilidad de profit factor;
- dispersión entre folds;
- sensibilidad a parámetros vecinos.

Con pocas operaciones, el resultado normal es `INSUFFICIENT_EVIDENCE`.

## 12. Múltiples pruebas y sobreajuste

Cada experimento registra `hypothesis_count` acumulado.

Aplicar, según el volumen de búsqueda:

- Benjamini-Hochberg/FDR para familias de hipótesis;
- Deflated Sharpe Ratio;
- Probability of Backtest Overfitting cuando sea viable;
- White Reality Check o SPA para comparación de muchas reglas;
- bootstrap/permutation frente a baseline.

Una mejora de una variante no se considera evidencia si solo aparece después de probar docenas de combinaciones y no sobrevive el ajuste.

## 13. Robustez

Una candidata debe mostrar:

- rendimiento no concentrado en un solo año;
- estabilidad en varios folds;
- resultado no dependiente de un único ticker;
- parámetros vecinos razonablemente similares;
- resistencia a costos 1.5x;
- ausencia de look-ahead/data leakage;
- drawdown dentro del presupuesto;
- benchmark superado en una métrica pre-registrada;
- test final no observado.

## 14. Análisis por régimen

Regímenes permitidos deben ser definidos por variables observables PIT, no por conocimiento posterior.

Reportar al menos:

- bull/bear/sideways;
- volatilidad alta/baja;
- tasas al alza/baja;
- risk-on/risk-off;
- para cripto: BTC liderazgo, ETH fortaleza relativa, debilidad amplia.

Los proxies deben etiquetarse como proxies y no como causalidad demostrada.

## 15. Strategy Brain

El cerebro debe:

- operar dentro de un `experiment_id`;
- generar IDs globalmente únicos;
- mantener train/validation/test separados;
- seleccionar padres solo con inner validation;
- evaluar el resultado final únicamente en outer test;
- usar `best_eligible`, no `best_overall`;
- contar hipótesis probadas;
- incluir capital inicial en drawdown;
- distinguir mejora de señal de simple reducción de notional;
- detenerse por convergencia o presupuesto;
- producir hipótesis, nunca promoción automática.

### Objetivo multiobjetivo recomendado

No optimizar PnL bruto. Usar una función pre-registrada con componentes normalizados, por ejemplo:

```text
score =
  + OOS excess return
  + expectancy stability
  + profit factor stability
  - max drawdown
  - tail loss
  - turnover/cost sensitivity
  - parameter complexity
  - concentration penalty
  - multiple-testing penalty
```

El valor exacto se versiona y se analiza por sensibilidad.

## 16. Criterios de promoción cuantitativa a shadow

Una candidata puede pasar de `BACKTEST_ONLY` a `SHADOW_ONLY` únicamente si:

- contratos de datos verdes;
- cero look-ahead detectado;
- test final bloqueado positivo en la métrica primaria;
- intervalo/robustez suficiente;
- supera baseline/benchmark según protocolo;
- costos stress no destruyen completamente el resultado;
- no depende de un único activo o periodo, salvo estrategia explícitamente individual;
- reporte firmado por una decisión humana.

## 17. Reporte estándar

Cada experimento publica:

```text
1. Hypothesis and pre-registration
2. Data snapshot and quality
3. Universe and corporate actions
4. Execution/cost model
5. Train/validation/test design
6. Hypothesis count and search procedure
7. Trade ledger checksum
8. Metrics by fold/year/asset/regime
9. Benchmarks
10. Uncertainty and multiple-testing adjustments
11. Sensitivity/stability
12. Failure analysis
13. Decision and allowed state
14. Reproduction command
```

## 18. Criterios de aceptación del framework

- misma entrada produce mismo checksum;
- un dato futuro cambia la prueba a rojo;
- el test final no es consultado durante tuning;
- resultados incluyen benchmarks y costos stress;
- métricas se validan contra fixtures calculados independientemente;
- cada hipótesis queda contada;
- el reporte distingue exploración de evidencia.
# 12 — Protocolo de optimización matemática por activo

## 1. Condición de inicio

Este protocolo permanece **BLOCKED** hasta aprobar WP-00 a WP-11 y Gates G1–G4. No se optimizan fórmulas sobre datos o backtests cuya semántica aún cambia.

## 2. Objetivo

Construir fórmulas interpretables y estables que se adapten a la naturaleza de cada grupo/activo sin caer en un conjunto de parámetros únicos sobreajustados a su historia.

La optimización debe responder:

- qué setup funciona;
- bajo qué régimen;
- con qué riesgo;
- para qué activo/grupo;
- con qué incertidumbre;
- frente a qué baseline;
- después de cuántas hipótesis probadas.

## 3. No optimizar cada ticker aisladamente al comienzo

Usar una jerarquía:

```text
global baseline
  -> asset-class model
    -> economic/profile group model
      -> asset-specific delta shrinked toward group
```

Fórmula conceptual:

```text
score(asset, t) = intercept_group
                + Σ beta_group_i * z_feature_i(t)
                + Σ delta_asset_i * z_feature_i(t)
                + allowed_regime_interactions
```

Con regularización:

```text
penalty = lambda_group * ||beta_group||
        + lambda_asset * ||delta_asset||
        + lambda_complexity * interactions
```

Si el activo no tiene muestra suficiente, `delta_asset -> 0` y usa la fórmula grupal.

## 4. Grupos iniciales propuestos

| Grupo | Activos ejecutables actuales | Universo research-only recomendado |
|---|---|---|
| MEGACAP_QUALITY_GROWTH | AAPL, META; MSFT cuando se habilite research | GOOGL, AMZN y peers versionados |
| SEMICONDUCTOR_AI | NVDA | AMD, AVGO, TSM, ASML, QCOM |
| CRYPTO_LINKED_EQUITY | COIN | HOOD, MSTR y miners solo como comparadores, no equivalentes perfectos |
| CRYPTO_MAJOR | BTC-USD, ETH-USD | índices/factores cripto PIT |
| DEFENSIVE_CONSUMER | KO, PG, PEP, WMT, COST, MCD | peers sectoriales PIT |
| HEALTHCARE_DEFENSIVE | JNJ | MRK, ABBV, PFE u otros peers PIT |
| QUALITY_PAYMENTS | V, MA | AXP/PYPL como comparadores con cautela |
| ESSENTIAL_SERVICES | WM | RSG y peers PIT |

El universo research-only también debe ser point-in-time y no se vuelve ejecutable automáticamente.

## 5. Familias de setup

No mezclar todos los comportamientos en una sola fórmula. Evaluar familias separadas:

1. `TREND_BREAKOUT`
2. `TREND_PULLBACK`
3. `SUPPORT_REBOUND`
4. `DEFENSIVE_MEAN_REVERSION`
5. `POST_EVENT_CONTINUATION`
6. `EVENT_AVOIDANCE`
7. `CRYPTO_REGIME_MOMENTUM`
8. `RELATIVE_STRENGTH_ROTATION`

Cada familia tiene un baseline simple. Solo luego se añaden interacciones.

## 6. Features

Todas las features deben ser PIT, robust-scaled y versionadas.

### Técnicas comunes

```text
returns 5/20/60/120
price vs SMA 20/50/200
SMA slopes
breakout distance
pullback depth
ATR/price
realized volatility
volume relative
52-week position
drawdown from high
relative strength vs benchmark
```

### Macro comunes

```text
SPY/QQQ/IWM returns
VIX level/change
10Y yield level/change
USD index/FX
credit/liquidity proxies si existen PIT
oil/gold/energy
risk-on/off score explícito
```

### Fundamentales acciones

```text
revenue growth PIT
margin trend PIT
FCF margin PIT
capex intensity PIT
debt/liquidity PIT
valuation vs own history and peers PIT
earnings/guidance event PIT
```

### Cripto

```text
BTC/ETH trend and relative strength
ETH/BTC
realized volatility
volume/liquidity
funding/open interest/stablecoin/exchange flows solo si se incorporan como PIT
regulatory/event data solo si es versionado
```

No usar ratios corporativos para BTC/ETH.

## 7. Priors y restricciones por grupo

### MEGACAP_QUALITY_GROWTH

- tendencia/momentum positivos pero limitados;
- valoración y FCF actúan como guardrails, no como timing único;
- sensibilidad a tasas/duración;
- earnings gap guard;
- delta por activo pequeño salvo evidencia.

### SEMICONDUCTOR_AI

- mayor peso a ciclo semiconductores, AI capex, volumen y volatilidad;
- fuerte penalización por evento/valoración extrema;
- stops/holding específicos de alta beta;
- exigir estabilidad en distintos ciclos.

### CRYPTO_LINKED_EQUITY

- BTC/ETH régimen y liquidez dominan sobre señales defensivas genéricas;
- regulación/eventos como riesgo, no causalidad inventada;
- separar riesgo de empresa y beta cripto;
- gap/cost stress elevado.

### CRYPTO_MAJOR

- fórmula independiente de acciones;
- BTC usa tendencia, volatilidad, drawdown y liquidez;
- ETH agrega fortaleza relativa ETH/BTC;
- no inferir altseason completa desde una sola métrica;
- evaluar 24/7 y costos cripto.

### DEFENSIVE_CONSUMER

- menor peso a breakout agresivo;
- pullback/mean reversion dentro de tendencia;
- tasas, USD, input costs y valoración;
- volatility target menor;
- distinguir COST/WMT de staples tradicionales y MCD.

### HEALTHCARE_DEFENSIVE

- calidad/valoración y tendencia;
- eventos regulatorios/legales PIT como guardrail;
- evitar pesos altos a noticias no históricas.

### QUALITY_PAYMENTS

- consumo/cross-border/rates;
- calidad y márgenes;
- trend pullback;
- V y MA comparten grupo con deltas pequeños.

### ESSENTIAL_SERVICES

- defensivo/quality;
- tasas y valoración;
- baja frecuencia;
- usar fórmula grupal si muestra individual insuficiente.

## 8. Parámetros optimizables

Separar bloques:

### Entrada

```text
feature weights
setup threshold
regime gates
event blackout window
relative strength requirement
```

### Riesgo

```text
risk per trade
max position
volatility target
stop ATR multiple
max gap tolerance
exposure/concentration limits
```

### Salida

```text
take profit R
trailing stop rule
time exit sessions
partial exit policy
invalidation condition
```

No cambiar entrada, sizing y salida simultáneamente en la primera búsqueda; dificulta atribución.

## 9. Objetivo multiobjetivo

Usar métricas outer-test normalizadas. Ejemplo conceptual:

```text
J = + median_oos_excess_return
    + expectancy_stability
    + profit_factor_stability
    + regime_consistency
    - max_drawdown_penalty
    - expected_shortfall_penalty
    - turnover_and_cost_penalty
    - parameter_instability_penalty
    - concentration_penalty
    - complexity_penalty
    - multiple_testing_penalty
```

Además usar restricciones duras:

```text
no look-ahead
minimum effective sample
max drawdown budget
cost stress survival
no single-fold dependency
no single-trade dependency
```

No permitir que reducir notional mejore artificialmente el score sin mejorar retorno por unidad de riesgo.

## 10. Algoritmo de búsqueda

### Fase A — sensibilidad univariada

- modificar un bloque a la vez;
- identificar direcciones estables;
- descartar features sin efecto consistente.

### Fase B — búsqueda acotada

- grid pequeño, random search con seed o Bayesian optimization acotada;
- presupuesto de hipótesis fijo;
- inner folds únicamente;
- regularización hacia baseline.

### Fase C — estabilidad

- superficie de parámetros vecinos;
- bootstrap;
- costos stress;
- subperiodos/regímenes;
- leave-one-asset-out para modelos grupales.

### Fase D — outer test

- evaluar una vez por fold;
- no retocar por resultado outer.

### Fase E — final locked test

- evaluar versión congelada;
- cualquier cambio posterior crea protocolo nuevo.

## 11. Minimum evidence floors

Estos son pisos de ingeniería, no garantía estadística:

- modelo grupal: muestra distribuida en varios activos y al menos dos outer folds;
- delta por activo: suficiente muestra efectiva para estimarlo y al menos dos ventanas fuera de muestra;
- cuando no exista muestra, delta = 0;
- ningún parámetro se acepta solo porque cruza un threshold puntual.

Como baseline inicial de configuración, se puede exigir 60 trades para siquiera estimar un delta y 20 trades outer-test distribuidos en dos folds, pero la incertidumbre puede exigir mucho más. El protocolo debe pre-registrar el mínimo según frecuencia y holding.

## 12. Shrinkage y regularización

Opciones aceptables:

- ridge/L2 para pesos;
- elastic net limitado;
- Bayesian hierarchical priors;
- partial pooling por grupo;
- monotonic constraints cuando exista una relación económica defensible.

Evitar modelos de alta capacidad hasta tener mucha más historia y datos PIT.

## 13. LLM en optimización

Permitido:

- proponer hipótesis;
- resumir fallos;
- sugerir qué evidencia falta;
- generar explicación estructurada.

Prohibido:

- elegir weights finales sin test;
- declarar `times_repeated`;
- autoasignar confidence como evidencia;
- autorizar aplicación;
- consultar final test durante tuning;
- inventar causalidad.

## 14. Promotion rule

Una fórmula específica reemplaza la grupal solo si:

- supera baseline en outer folds y locked test según métrica primaria;
- no empeora materialmente riesgo/cola;
- sobrevive costos stress;
- parámetros vecinos son estables;
- no depende de un evento/ticker/periodo aislado;
- multiple-testing adjusted evidence es aceptable;
- shadow confirma distribución/operación;
- paper confirma fills/slippage cuando corresponda;
- aprobación humana.

En caso contrario, conservar la fórmula más simple.

## 15. Reporte por activo

```text
asset/group
formula family
baseline formula
candidate formula
feature coefficients and priors
data/folds
hypothesis count
OOS metrics
benchmark comparison
uncertainty
cost sensitivity
parameter neighborhood
regime breakdown
concentration analysis
shadow/paper evidence
decision
```

## 16. Criterio de éxito

El éxito no es producir una fórmula distinta para cada activo. El éxito es demostrar cuándo una fórmula grupal es suficiente y cuándo existe evidencia real para un ajuste individual.
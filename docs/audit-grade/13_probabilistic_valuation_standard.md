# 13 — Estándar de valoración probabilística y decisión con IA

## Estado

```text
work_package: WP-07A
issue: #65
implementation_mode: PURE_PYTHON_RESEARCH_CORE
operating_mode: BACKTEST_ONLY
promotion_mode: SHADOW_ONLY
production_change_allowed: false
```

## 1. Objetivo

El sistema no puede llamar `BARATA`, `PRECIO_JUSTO` o `CARA` a una acción
sumando indiscriminadamente múltiplos, márgenes, calidad y momentum. WP-07A
separa cuatro preguntas:

1. **Valoración:** qué distribución de fair value producen modelos aplicables.
2. **Calidad:** qué tan sólido es el negocio, sin alterar el fair value.
3. **Value trap:** qué probabilidad existe de deterioro material.
4. **Incertidumbre:** si la evidencia permite clasificar o exige abstención.

La salida no es un precio objetivo puntual. Es una distribución:

```text
fair_value_p10
fair_value_p25
fair_value_p50
fair_value_p75
fair_value_p90
```

## 2. Límites de confianza

El núcleo de `packages/valuation/` es puro y sin efectos laterales:

- no lee ni escribe BigQuery;
- no llama redes, brokers, LLMs ni APIs externas;
- no crea órdenes;
- no despliega;
- no promociona;
- no contiene reglas por ticker;
- toda salida mantiene `production_change_allowed=false`.

La integración con datos live se bloquea hasta que WP-03 y WP-04 entreguen
fundamentales y precios PIT aprobados.

## 3. Contrato de lineage

Cada modelo declara:

```text
data_snapshot_id
feature_set_version
model_version
source_cutoff_at
currency
peer_universe_hash
configuration_hash
```

Un ensemble solo combina modelos con el mismo:

```text
data_snapshot_id
feature_set_version
source_cutoff_at
currency
```

Una incompatibilidad produce `DATOS_INSUFICIENTES`; nunca se corrige
silenciosamente.

## 4. Valoración relativa

WP-07A implementa un baseline robusto:

```text
log(multiple)
=
intercept
+ beta * robust_z(fundamentals)
+ residual
```

Propiedades:

- features estandarizadas por mediana y MAD;
- ridge regression determinística;
- residual empírico para construir incertidumbre;
- extrapolación fuera de peers registrada;
- soporte inicial para `PE`, `PS`, `PB`, `P_FCF` y `EV_EBITDA`;
- `EV_EBITDA` convierte enterprise value a equity value con deuda neta;
- múltiplos o anchors no positivos fallan cerrados.

El score relativo es positivo cuando el múltiplo observado está por debajo del
múltiplo explicado por peers y fundamentales. No incorpora directamente el
score de calidad.

## 5. Valor intrínseco

### FCFF por escenarios

Cada escenario declara:

```text
base_fcff
growth_rates
discount_rate
terminal_growth_rate
net_debt
shares_outstanding
probability
```

Se exigen al menos tres escenarios para producir una distribución. El
crecimiento terminal debe ser menor al descuento.

### Residual income

Ruta inicial para negocios donde book value y ROE son económicamente
informativos:

```text
equity value
=
book value
+ PV(ROE * book - cost_of_equity * book)
+ terminal residual income
```

### Reverse DCF

Resuelve por bisección el crecimiento explícito implícito en el precio. Si el
precio no puede reproducirse dentro de los bounds aprobados, devuelve
`feasible=false`; no amplía los bounds para obtener una respuesta.

## 6. Calidad y value trap

La calidad usa, cuando están disponibles:

- gross profitability;
- `ROIC - WACC`;
- free-cash-flow margin;
- cash conversion;
- estabilidad de márgenes;
- interest coverage;
- net debt / EBITDA.

El riesgo de value trap usa señales independientes:

- revisiones negativas;
- deterioro de margen;
- leverage;
- cobertura de intereses;
- accruals;
- FCF negativo;
- contracción de revenue.

Regla central:

> calidad alta no transforma una valoración cara en económica.

La calidad puede reducir incertidumbre. Un value-trap risk alto puede bloquear
la etiqueta `ECONOMICA` o forzar abstención, pero no cambia los quantiles de
fair value.

## 7. Ensemble

Cada modelo aporta una distribución de cinco quantiles, confidence, peso,
score y lineage. El ensemble crea una mezcla determinística y calcula:

```text
model_agreement_score
valuation_confidence
probability_economic
probability_expensive
expected_return_p10/p50/p90
```

La política inicial está versionada en:

```text
config/valuation/wp07a_policy_v1.json
```

Los thresholds son parámetros auditables, no hechos universales.

### Clasificación inicial

`ECONOMICA` exige:

- número mínimo de modelos;
- lineage compatible;
- confidence mínima;
- intervalo no excesivamente ancho;
- probabilidad suficiente de fair value al menos 15% sobre el precio;
- value-trap probability bajo el máximo permitido.

`CARA` exige probabilidad suficiente de fair value al menos 15% bajo el precio.

`PRECIO_JUSTO` exige mediana dentro de la banda de política o precio dentro del
intervalo central.

Cualquier conflicto material devuelve `DATOS_INSUFICIENTES`.

## 8. Calibración

WP-07A incluye:

- Brier score;
- log loss;
- expected calibration error;
- maximum calibration error;
- coverage de intervalos;
- conformal absolute error;
- expansión de intervalos.

Una muestra menor al mínimo produce `INSUFFICIENT`, nunca `PASS`.

## 9. Rutas por tipo de activo

La integración posterior debe enrutar:

| Tipo | Modelos principales |
|---|---|
| Banco/aseguradora | residual income y P/B condicionado por ROE |
| Empresa no financiera estable | FCFF + relative multiples |
| Alto crecimiento | reverse DCF + EV/Sales condicionado |
| Cíclica/commodity | márgenes y cash flows normalizados de ciclo |
| REIT | NAV/AFFO |
| ETF | NAV/tracking; no valuation corporativa |
| Cripto | modelo separado; no P/E, P/B ni DCF corporativo |

Una ruta no implementada devuelve `NOT_APPLICABLE` o `DATOS_INSUFICIENTES`.

## 10. Relación con otros work packages

- **WP-03:** fundamentales y earnings PIT.
- **WP-04:** precios, corporate actions, sesiones y FX PIT.
- **WP-05:** fills, capital, costos y ledger.
- **WP-06:** Strategy Brain aislado.
- **WP-07:** nested walk-forward, bootstrap y multiple testing.
- **WP-07A / #65:** valoración probabilística.
- **WP-07B / #66:** ML de alpha y NLP estructurado.
- **WP-07C / #67:** optimización de cartera neta de costos.
- **WP-08:** risk gate y executor determinístico.
- **WP-12:** deltas por activo solo después de aprobar los gates.

## 11. Gates para integración

La materialización Dataform de WP-07A solo puede comenzar cuando:

1. WP-03 y WP-04 estén fusionados y validados;
2. exista `valuation_features_pit`;
3. todos los inputs tengan `available_at <= signal_timestamp`;
4. modelos/peers/policy tengan versiones y hashes;
5. el resultado sea shadow-only;
6. WP-07 valide calibración y estabilidad OOS.

## 12. Definition of Done

WP-07A no está completo solo porque las fórmulas compilen. Requiere:

- núcleo Python y pruebas verdes;
- integración PIT;
- calibración OOS;
- comparación contra el clasificador heurístico;
- interval coverage aceptable;
- abstención correcta;
- evidencia y replay por snapshot/config;
- revisión independiente;
- cero camino hacia órdenes o promoción.

# 13 — Estándar de valoración probabilística y decisión con IA

## Estado

```text
work_package: WP-07A
issue: #65
implementation_mode: PURE_PYTHON_RESEARCH_CORE
operating_mode: BACKTEST_ONLY
promotion_mode: SHADOW_ONLY
production_change_allowed: false
policy_version: wp07a-valuation-policy-v2
```

## 1. Objetivo

El sistema no puede llamar `ECONOMICA`, `PRECIO_JUSTO` o `CARA` a una
acción sumando indiscriminadamente múltiplos, márgenes, calidad y momentum.
WP-07A separa cuatro preguntas:

1. **Valoración:** qué distribución de fair value producen modelos aplicables.
2. **Calidad:** qué tan sólido es el negocio, sin alterar el fair value.
3. **Value trap:** qué riesgo existe de deterioro material.
4. **Incertidumbre:** si existe evidencia calibrada para clasificar o se debe
   devolver `DATOS_INSUFICIENTES`.

La salida válida es una distribución, no un precio objetivo puntual:

```text
fair_value_p10
fair_value_p25
fair_value_p50
fair_value_p75
fair_value_p90
```

Si el ensemble no puede construir una distribución válida, esos campos son
`NULL`/`None`. Nunca se sustituyen silenciosamente por el precio actual.

## 2. Límites de confianza

El núcleo de `packages/valuation/` es puro y sin efectos laterales:

- no lee ni escribe BigQuery;
- no llama redes, brokers, LLMs ni APIs externas;
- no crea órdenes;
- no despliega;
- no promociona;
- no contiene reglas por ticker;
- toda salida mantiene `production_change_allowed=false`.

La integración live permanece bloqueada hasta que WP-03 y WP-04 entreguen
fundamentales y precios PIT aprobados.

## 3. Precio y lineage point-in-time

Cada clasificación recibe un `PriceObservation` con:

```text
price
observed_at
available_at
currency
data_snapshot_id
source_hash
```

Cada modelo y el assessment de calidad declaran:

```text
data_snapshot_id
feature_set_version
model_version
source_cutoff_at
currency
configuration_hash
peer_universe_hash, cuando aplica
```

Reglas fail-closed:

- `available_at <= source_cutoff_at`;
- precio, modelos y calidad usan el mismo snapshot y moneda;
- todos los modelos del ensemble comparten snapshot, feature set, cutoff y
  moneda;
- el configuration hash debe corresponder a los parámetros realmente usados;
- una incompatibilidad devuelve `DATOS_INSUFICIENTES` sin fair value fabricado.

El resultado conserva:

```text
price_observation_hash
policy_hash
quality_assessment_hash
model_hashes
result_hash
```

## 4. Valoración relativa

El baseline relativo implementa:

```text
log(multiple)
=
intercept
+ beta * robust_z(fundamentals)
+ residual
```

Controles obligatorios:

- features estandarizadas por mediana y MAD;
- ridge regression determinística con intercept no penalizado;
- incertidumbre y métricas de fit calculadas con leave-one-out, no con residuos
  in-sample;
- mínimo de peers proporcional al número de parámetros, incluyendo cada fold
  leave-one-out;
- tickers peer únicos;
- el ticker sujeto no puede incluirse entre sus propios peers;
- el `peer_universe_hash` debe coincidir con las observaciones exactas;
- el `configuration_hash` incluye métrica, features, ridge, sample floor y
  regla de extrapolación;
- extrapolación fuera del universo comparable queda registrada;
- soporte para `PE`, `PS`, `PB`, `P_FCF` y `EV_EBITDA`;
- `EV_EBITDA` convierte enterprise value a equity value con deuda neta;
- múltiplos, anchors o equity value no positivos fallan cerrados.

La validación leave-one-out no reemplaza calibración OOS. Cada distribución
relativa nace con `calibration_status=UNVERIFIED`.

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

Se exigen al menos tres escenarios, nombres únicos y probabilidades que sumen
exactamente uno dentro de tolerancia numérica. El crecimiento terminal debe ser
menor al descuento. El hash de configuración contiene todos los escenarios.

### Residual income

Para entidades donde book value y ROE son informativos:

```text
equity value
=
book value
+ PV(ROE * book - cost_of_equity * book)
+ terminal residual income
```

Una pérdida genera dividendo cero. Nunca se interpreta el payout sobre
beneficios negativos como un dividendo negativo o una inyección automática de
capital.

### Reverse DCF

Resuelve por bisección el crecimiento explícito implícito en el precio. Si el
precio no puede reproducirse dentro de bounds aprobados, devuelve
`feasible=false`; no amplía los bounds para fabricar una solución.

Los modelos por escenarios nacen `UNVERIFIED` y no votan en clasificación
hasta ligar evidencia OOS.

## 6. Calidad y value trap

La calidad usa, cuando están disponibles:

- gross profitability;
- `ROIC - WACC`;
- free-cash-flow margin;
- cash conversion;
- estabilidad de márgenes;
- interest coverage;
- net debt / EBITDA.

El riesgo de value trap usa señales separadas:

- revisiones negativas;
- deterioro de margen;
- leverage;
- cobertura de intereses;
- accruals;
- FCF negativo;
- contracción de revenue.

Reglas centrales:

- calidad alta no transforma una acción cara en económica;
- el score de value trap heurístico no se presenta como bajo riesgo hasta
  contar con calibración OOS;
- un warning alto puede bloquear conservadoramente antes de calibración;
- `ECONOMICA` requiere cobertura suficiente y evidencia de calibración del
  modelo de value trap cuando la política lo exige;
- calidad y riesgo nunca modifican los quantiles de fair value.

## 7. Evidencia de calibración

Los reportes incluyen:

- Brier score;
- log loss;
- expected y maximum calibration error;
- interval coverage;
- mean interval width;
- tamaño de muestra bruto;
- tamaño de muestra efectivo ante observaciones ponderadas;
- conformal absolute error y expansión de intervalos.

Una muestra pequeña o dominada por pocos pesos produce `INSUFFICIENT`, nunca
`PASS`.

`ModelCalibrationEvidence` liga criptográficamente:

```text
model_spec_hash
calibration_snapshot_id
evaluation_split_id
target_definition_hash
calibration_cutoff_at
probability_report_hash
interval_report_hash
```

El ensemble verifica el registro de evidencia y exige que todos los modelos se
hayan calibrado sobre el mismo split OOS y target. Un hash arbitrario no basta.

`RiskCalibrationEvidence` realiza el mismo control para el modelo de value
trap.

## 8. Ensemble

Cada modelo aporta una distribución de cinco quantiles, score, confidence,
lineage y calibración. El peso de cada familia pertenece exclusivamente a la
política; el payload del modelo no puede escoger su propio peso.

Controles:

- model names, model specs y model families únicos;
- route por tipo de entidad;
- lineage compatible;
- evidencia OOS ligada al model spec;
- pesos de política versionados;
- mezcla determinística;
- tails explícitamente winsorizadas en p10/p90 y reason code visible;
- quality/value-trap solo afectan confianza o abstención;
- resultado y razón de abstención hasheados.

La política está versionada en:

```text
config/valuation/wp07a_policy_v2.json
```

### Clasificación

`ECONOMICA` exige:

- número y familias mínimas de modelos;
- evidencia OOS válida;
- lineage compatible;
- confidence mínima;
- intervalo no excesivamente ancho;
- probabilidad suficiente de fair value al menos 15% sobre el precio;
- cobertura y calibración suficientes del value-trap model;
- value-trap probability bajo el máximo permitido.

`CARA` exige probabilidad suficiente de fair value al menos 15% bajo el precio.

`PRECIO_JUSTO` exige mediana dentro de la banda de política o precio dentro del
intervalo central.

Cualquier conflicto material devuelve `DATOS_INSUFICIENTES`.

## 9. Rutas por tipo de activo

| Tipo | Modelos principales |
|---|---|
| Banco/aseguradora | residual income y P/B condicionado por ROE |
| Empresa no financiera estable | FCFF + relative multiples |
| Alto crecimiento | reverse DCF diagnóstico + EV/Sales condicionado |
| Cíclica/commodity | márgenes y cash flows normalizados de ciclo |
| REIT | NAV/AFFO |
| ETF | NAV/tracking; no valoración corporativa |
| Cripto | modelo separado; no P/E, P/B ni DCF corporativo |

Una ruta incompleta devuelve `DATOS_INSUFICIENTES`.

## 10. Relación con otros work packages

- **WP-03:** fundamentales y earnings PIT.
- **WP-04:** precios, corporate actions, sesiones y FX PIT.
- **WP-05:** fills, capital, costos y ledger.
- **WP-06:** Strategy Brain aislado.
- **WP-07:** nested walk-forward, calibración OOS y multiple testing.
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
4. modelos, peers, price observation y policy tengan hashes verificables;
5. el resultado permanezca shadow-only;
6. WP-07 genere evidencia OOS compatible y registrada;
7. exista comparación contra el clasificador heurístico legacy.

## 12. Definition of Done

El núcleo de código puede obtener `CODE PASS`, pero WP-07A completo requiere:

- integración PIT;
- calibración OOS;
- comparación shadow contra legacy;
- interval coverage aceptable;
- estabilidad por fold, activo y régimen;
- evidencia y replay por snapshot/config;
- revisión independiente;
- cero camino hacia órdenes o promoción.

# 02 — Contratos de datos y point-in-time

## 1. Regla central

Una observación es elegible para una señal únicamente cuando:

```sql
available_at <= signal_timestamp
```

`period_end_date`, `earnings_date`, `snapshot_date` o la fecha del evento económico no sustituyen `available_at`.

## 2. Tiempos estándar

| Campo | Significado |
|---|---|
| `event_time` | Momento económico del evento. |
| `available_at` | Primer instante en que la información era públicamente utilizable. |
| `source_published_at` | Fecha/hora declarada por la fuente. |
| `ingested_at` | Fecha/hora en que el sistema recibió la fila. |
| `valid_from` / `valid_to` | Vigencia de una revisión normalizada. |
| `signal_timestamp` | Instante de decisión del sistema. |
| `execution_timestamp` | Instante de envío/fill del broker. |

Todas las timestamps se guardan en UTC. La zona horaria original se conserva en una columna separada.

## 3. Contrato de precios

### 3.1 Tabla raw

`market_price_raw`

```text
raw_record_id STRING NOT NULL
ingestion_run_id STRING NOT NULL
source STRING NOT NULL
source_version STRING
source_ticker STRING NOT NULL
exchange STRING
asset_type STRING NOT NULL
source_interval STRING NOT NULL
source_timezone STRING
event_timestamp TIMESTAMP NOT NULL
open NUMERIC
high NUMERIC
low NUMERIC
close NUMERIC
adj_close NUMERIC
volume NUMERIC
currency STRING
payload_json STRING
payload_hash STRING NOT NULL
received_at TIMESTAMP NOT NULL
```

Clave lógica: `source + source_ticker + source_interval + event_timestamp + revision`.

### 3.2 Tabla canónica

`market_price_canonical`

```text
price_id STRING NOT NULL
ticker STRING NOT NULL
asset_type STRING NOT NULL
exchange STRING
session_date DATE NOT NULL
bar_start TIMESTAMP NOT NULL
bar_end TIMESTAMP NOT NULL
canonical_interval STRING NOT NULL
raw_open NUMERIC
raw_high NUMERIC
raw_low NUMERIC
raw_close NUMERIC
adjusted_close NUMERIC
raw_volume NUMERIC
split_factor NUMERIC
dividend_amount NUMERIC
currency STRING
source STRING NOT NULL
source_interval STRING NOT NULL
coverage_ratio FLOAT64
quality_status STRING NOT NULL
selected_by_rule STRING NOT NULL
data_snapshot_id STRING NOT NULL
available_at TIMESTAMP NOT NULL
ingested_at TIMESTAMP NOT NULL
```

### 3.3 Regla de selección diaria

Para cada ticker/sesión:

1. Preferir intradía únicamente si la cobertura supera el umbral esperado del calendario.
2. Si la cobertura intradía es incompleta, usar la vela diaria de la fuente.
3. Nunca agregar simultáneamente la vela diaria y las velas intradía.
4. Registrar `selected_by_rule` y `coverage_ratio`.
5. Para cripto, definir explícitamente día UTC y barras 4h.

### 3.4 Raw vs adjusted

- entradas, stops, take profits, gaps y fills usan `raw_*`;
- retornos, medias y benchmarks usan `adjusted_close`;
- todo resultado declara qué serie utilizó.

## 4. Corporate actions

Tabla `corporate_actions_pit`:

```text
action_id STRING NOT NULL
ticker STRING NOT NULL
action_type STRING NOT NULL  -- SPLIT, DIVIDEND, SYMBOL_CHANGE, MERGER
ex_date DATE
record_date DATE
pay_date DATE
ratio NUMERIC
cash_amount NUMERIC
currency STRING
source STRING NOT NULL
source_record_id STRING
source_published_at TIMESTAMP
available_at TIMESTAMP NOT NULL
ingested_at TIMESTAMP NOT NULL
revision INT64 NOT NULL
quality_status STRING NOT NULL
```

Pruebas obligatorias:

- split 2:1 conserva continuidad del adjusted return;
- raw price se mantiene apto para ejecución;
- dividendo no aparece como caída económica en retorno total;
- revisión posterior no reescribe una corrida histórica sin cambiar `data_snapshot_id`.

## 5. Fundamentales point-in-time

### 5.1 Problema que se corrige

El productor actual guarda `report_date = NULL`; los modelos usan `period_end_date` como fallback. Esto permite que el backtest conozca un filing antes de su publicación.

### 5.2 Tabla normalizada

`financial_statements_pit`

```text
statement_id STRING NOT NULL
ticker STRING NOT NULL
fiscal_period STRING NOT NULL
fiscal_year INT64 NOT NULL
fiscal_quarter INT64
period_start DATE
period_end_date DATE NOT NULL
filing_date DATE
source_published_at TIMESTAMP
available_at TIMESTAMP NOT NULL
form_type STRING
currency STRING
revenue NUMERIC
gross_profit NUMERIC
operating_income NUMERIC
net_income NUMERIC
eps_basic NUMERIC
eps_diluted NUMERIC
total_assets NUMERIC
total_liabilities NUMERIC
total_debt NUMERIC
shareholders_equity NUMERIC
operating_cash_flow NUMERIC
capital_expenditures NUMERIC
free_cash_flow NUMERIC
source STRING NOT NULL
source_record_id STRING
revision INT64 NOT NULL
is_restated BOOL NOT NULL
quality_status STRING NOT NULL
ingested_at TIMESTAMP NOT NULL
```

### 5.3 Fuente y prioridad

Orden recomendado para acciones estadounidenses:

1. SEC filing timestamp / company investor relations publication.
2. Proveedor financiero con timestamp de publicación verificable.
3. Yahoo únicamente como contraste o fallback marcado.

Un fallback sin fecha verificable recibe `quality_status = UNVERIFIED_AVAILABLE_AT` y no es elegible para backtest PIT.

### 5.4 Cálculo YoY correcto

Primero deduplicar la serie trimestral:

```sql
WITH versioned AS (
  SELECT * EXCEPT(rn)
  FROM (
    SELECT *,
      ROW_NUMBER() OVER (
        PARTITION BY ticker, fiscal_year, fiscal_quarter
        ORDER BY revision DESC, available_at DESC, ingested_at DESC
      ) rn
    FROM financial_statements_pit
    WHERE available_at <= @signal_timestamp
  )
  WHERE rn = 1
), quarterly AS (
  SELECT *,
    LAG(revenue, 4) OVER (
      PARTITION BY ticker
      ORDER BY fiscal_year, fiscal_quarter
    ) AS revenue_same_quarter_prior_year
  FROM versioned
)
SELECT *,
  SAFE_DIVIDE(revenue - revenue_same_quarter_prior_year,
              revenue_same_quarter_prior_year) AS revenue_yoy
FROM quarterly
```

Después realizar el join as-of-date con cada señal. Nunca calcular `LAG` después de multiplicar estados por fechas de precio.

## 6. Ratios point-in-time

`financial_ratios_snapshot` debe incorporar:

```text
available_at TIMESTAMP NOT NULL
source_published_at TIMESTAMP
underlying_statement_id STRING
price_timestamp TIMESTAMP
calculation_version STRING
```

Los ratios derivados deben recalcularse internamente desde estados PIT y precios PIT cuando sea posible. Los ratios del proveedor se conservan como observación externa, no como única fuente.

## 7. Earnings point-in-time

Separar:

- calendario esperado;
- publicación real;
- valores reportados;
- revisiones.

Tabla `earnings_events_pit`:

```text
earnings_event_id STRING NOT NULL
ticker STRING NOT NULL
fiscal_period STRING
event_type STRING NOT NULL -- SCHEDULED, RESCHEDULED, REPORTED
event_timestamp TIMESTAMP
source_published_at TIMESTAMP
available_at TIMESTAMP NOT NULL
eps_estimate NUMERIC
reported_eps NUMERIC
revenue_estimate NUMERIC
reported_revenue NUMERIC
surprise_pct FLOAT64
guidance_json STRING
source STRING NOT NULL
revision INT64 NOT NULL
quality_status STRING NOT NULL
ingested_at TIMESTAMP NOT NULL
```

Una fecha anunciada hoy no puede existir retroactivamente en un backtest anterior a su anuncio.

## 8. Macro y noticias

Cada serie macro debe distinguir:

```text
observation_period
release_timestamp
available_at
revision/vintage
```

Para indicadores económicos revisables se debe usar la vintage disponible en el momento, no el valor revisado actual.

Las noticias recientes no deben rellenarse hacia atrás. Los proxies deben tener nombres explícitos y una columna `context_source = REAL | PROXY | MISSING`.

## 9. Universo point-in-time

Tabla `asset_universe_membership`:

```text
universe_version STRING NOT NULL
ticker STRING NOT NULL
valid_from DATE NOT NULL
valid_to DATE
membership_reason STRING
liquidity_eligible BOOL
execution_eligible BOOL
source STRING
available_at TIMESTAMP NOT NULL
```

Toda corrida fija `universe_version`. Cambiar activos crea una nueva versión y no reescribe resultados anteriores.

## 10. Experiment registry

Tabla `experiment_runs`:

```text
experiment_id STRING NOT NULL
parent_experiment_id STRING
created_at TIMESTAMP NOT NULL
status STRING NOT NULL
hypothesis STRING NOT NULL
git_sha STRING NOT NULL
image_digest STRING
dataform_compilation_id STRING
data_snapshot_id STRING NOT NULL
universe_version STRING NOT NULL
feature_set_version STRING NOT NULL
strategy_version STRING NOT NULL
execution_model_version STRING NOT NULL
cost_model_version STRING NOT NULL
configuration_json STRING NOT NULL
configuration_hash STRING NOT NULL
dependency_lock_hash STRING NOT NULL
random_seed INT64
train_start DATE
train_end DATE
validation_start DATE
validation_end DATE
test_start DATE
test_end DATE
hypothesis_count INT64 NOT NULL
production_change_allowed BOOL NOT NULL
results_checksum STRING
completed_at TIMESTAMP
```

No usar `candidate_id` como sustituto de `experiment_id`.

## 11. Identificadores

IDs determinísticos recomendados:

```text
ingestion_run_id = UUID
price_id = SHA256(source|ticker|interval|event_timestamp|revision)
statement_id = SHA256(source|ticker|period|filing_date|revision)
experiment_id = UUID
candidate_id = SHA256(experiment_id|generation|parent_candidate_id|candidate_config_hash)
trade_id = SHA256(experiment_id|candidate_id|strategy_version|ticker|signal_timestamp)
order_intent_id = UUID
client_order_id = stable hash(order_intent_id)
```

Todas las uniones del Strategy Brain deben usar `experiment_id/run_id + candidate_id`, nunca únicamente `candidate_id`.

## 12. Data quality gates

Un `data_snapshot_id` solo se publica cuando pasan:

- unicidad;
- nulidad;
- dominios;
- continuidad esperada;
- cobertura de sesiones;
- ausencia de mezcla 1d/intradía;
- corporate actions reconciliadas;
- timestamps PIT válidas;
- source freshness;
- reconciliación entre fuentes dentro de tolerancia;
- checksum estable.

## 13. Reconciliación de fuentes

Incorporar una segunda fuente para precios y, al menos, filings/earnings.

La reconciliación produce:

```text
MATCH
WITHIN_TOLERANCE
MATERIAL_MISMATCH
SOURCE_MISSING
STALE_SOURCE
```

Un mismatch material bloquea señales del ticker hasta resolución o degradación manual documentada.

## 14. Plan de migración

1. Crear tablas PIT nuevas sin tocar legacy.
2. Añadir `available_at` y metadatos a productores.
3. Backfill desde fuentes verificables.
4. Marcar filas sin disponibilidad verificable.
5. Crear modelos canónicos nuevos.
6. Añadir fixtures y pruebas no-look-ahead.
7. Ejecutar dual-run legacy vs audit-grade.
8. Generar informe de diferencias.
9. Cambiar consumidores de research.
10. Etiquetar resultados previos `LEGACY_PRE_AUDIT_GRADE`.
11. Mantener rollback hacia legacy mientras todo permanezca shadow.

## 15. Criterios de aceptación

- Cero filas utilizadas con `available_at > signal_timestamp`.
- YoY validado contra fixtures independientes.
- Cero mezcla de granularidades en vela canónica.
- Splits/dividendos reproducibles.
- Todo experimento vinculado a un snapshot inmutable.
- Cualquier revisión de fuente crea una nueva versión/snapshot.
- Los contratos fallan de forma visible y bloquean publicación.
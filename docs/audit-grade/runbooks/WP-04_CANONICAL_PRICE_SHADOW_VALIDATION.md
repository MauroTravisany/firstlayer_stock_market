# WP-04 — Validación shadow de precios canónicos

## 1. Objetivo

Demostrar en BigQuery, sin modificar producción, que WP-04 construye una serie
de precios reproducible y point-in-time con:

- revisiones raw append-only;
- intervalos, timezone, exchange, run ID y payload hash explícitos;
- sesiones XNYS, FX 24/5 y cripto 24/7;
- exactamente una granularidad por barra canónica;
- OHLC raw para ejecución y adjusted close para retornos;
- corporate actions históricas sin timestamp verificable retenidas fail-closed;
- reconciliación Yahoo/Stooq;
- USD/CLP histórico;
- features, dual-run y assertion exclusivamente shadow.

Este runbook no autoriza producción, Paper Champion ni dinero real.

## 2. Identidad inmutable

Antes de cualquier operación, registrar:

```text
FINAL_SHA=<SHA aprobado por ChatGPT>
CI_RUN_ID=<CI exitoso del mismo SHA>
PROJECT_ID=stocks-437902
LOCATION=us-east1
OPERATIONAL_DATASET=acciones_dataset
ASSET_SET=config/wp04_shadow_assets.v1.json
```

El checkout debe estar detached, exactamente en `FINAL_SHA` y limpio. Todo
plan, checksum, candidate branch, compilation result o evidencia de otro SHA es
obsoleto.

## 3. Estado de seguridad obligatorio

Verificar read-only:

- PR WP-04 abierto y draft;
- CI del SHA exacto en `success`;
- deploy Cloud Run deshabilitado;
- Strategy Brain generate/review `PAUSED`;
- Strategy Brain `BACKTEST_ONLY`;
- champion/challenger `SHADOW_ONLY`;
- Alpaca Paper;
- ningún workflow productivo en ejecución.

Detenerse ante cualquier discrepancia.

## 4. Datasets aislados

Crear dos datasets nuevos con sufijo UTC.

Schema-check:

```text
acciones_dataset_shadow_wp04_schema_<UTC>
location=us-east1
environment=shadow
work_package=wp04
purpose=compiled_sql_validation
```

Shadow real:

```text
acciones_dataset_shadow_wp04_<UTC>
location=us-east1
environment=shadow
work_package=wp04
purpose=canonical_price_validation
```

No borrar ni reutilizar datasets cuyo lineage sea incierto. Ambos deben estar
vacíos antes de comenzar.

## 5. Candidate branch Dataform

El repositorio Dataform conectado espera `dataform/` como raíz. Crear una
candidate branch temporal cuyo árbol sea exactamente:

```text
$FINAL_SHA:dataform
```

No mover `dataform-production`, no actualizar release config production y no
reutilizar una candidate branch anterior.

## 6. Compilation result de schema-check

Crear una compilation result nueva con:

```text
defaultDatabase = stocks-437902
defaultSchema = acciones_dataset
defaultLocation = us-east1
assertionSchema = <SCHEMA_DATASET>

vars.auditDataset = <SCHEMA_DATASET>
vars.operationalDataset = acciones_dataset
vars.environment = shadow
vars.useCanonicalPrices = "true"
vars.minimumIntradayCoverage = "0.95"
vars.requireSecondaryPriceSource = "false"
vars.priceCloseToleranceBps = "10"
vars.priceVolumeToleranceRatio = "0.10"
vars.priceSourceStaleSeconds = "86400"
vars.usdClpTicker = "CLP=X"
vars.priceModelVersion = "wp04-canonical-prices-v1"
```

La única dependencia operacional autorizada es
`acciones_dataset.trading_price_features`, read-only, para el dual-run y el
rollback bridge. Todos los outputs y assertions WP-04 deben apuntar al dataset
schema-check.

## 7. Exportar actions completas

Consultar paginadamente todas las `CompilationResultActions`, conservando:

- action type;
- target y canonical target;
- dependencies y parent action;
- file path;
- SQL compilado íntegro.

Guardar fuera del checkout:

```text
/tmp/wp04-shadow-evidence/wp04_schema_compilation_actions.json
```

El conjunto requerido es:

```text
3 operations
6 relations
1 required assertion
```

Acciones requeridas:

```text
market_price_raw
corporate_actions_pit
market_session_calendar
price_source_reconciliation
market_price_canonical
fx_rates_pit
trading_price_features_canonical_shadow
trading_price_features_wp04_shadow
wp04_legacy_vs_canonical_shadow
audit_canonical_prices
```

## 8. Schema graph preventivo

Plan:

```bash
python tools/wp04_compiled_sql_schema_check.py \
  --actions-json /tmp/wp04-shadow-evidence/wp04_schema_compilation_actions.json \
  --expected-git-sha "$FINAL_SHA" \
  --compilation-result "$SCHEMA_COMPILATION_RESULT" \
  --project-id "$PROJECT_ID" \
  --operational-dataset "$OPERATIONAL_DATASET" \
  --validation-dataset "$SCHEMA_DATASET" \
  --location "$LOCATION" \
  --environment shadow \
  --output /tmp/wp04-shadow-evidence/wp04_schema_graph_plan.json
```

Revisar todos los targets, layers, SQL hashes y dependencias. Extraer el
`plan_checksum` y ejecutar:

```bash
python tools/wp04_compiled_sql_schema_check.py \
  --actions-json /tmp/wp04-shadow-evidence/wp04_schema_compilation_actions.json \
  --expected-git-sha "$FINAL_SHA" \
  --compilation-result "$SCHEMA_COMPILATION_RESULT" \
  --project-id "$PROJECT_ID" \
  --operational-dataset "$OPERATIONAL_DATASET" \
  --validation-dataset "$SCHEMA_DATASET" \
  --location "$LOCATION" \
  --environment shadow \
  --execute \
  --expected-plan-checksum "$WP04_SCHEMA_PLAN_CHECKSUM" \
  --acknowledge-validation-write WP04_SCHEMA_VALIDATION_WRITE \
  --output /tmp/wp04-shadow-evidence/wp04_schema_graph_result.json
```

Gate obligatorio:

```text
status = ALL_COMPILED_ACTIONS_SCHEMA_GRAPH_PASS
required_action_count = 10
operations = 3
relations = 6
assertions = 1
failed_action_count = 0
failed_assertion_count = 0
validation_dataset_only = true
production_change_allowed = false
```

No continuar ante un solo FAIL o BLOCKED.

## 9. Compilation result del shadow real

Crear una segunda compilation result desde el mismo snapshot. Cambiar únicamente:

```text
vars.auditDataset = <REAL_SHADOW_DATASET>
assertionSchema = <REAL_SHADOW_DATASET>
```

Mantener `vars.useCanonicalPrices="true"`. Comparar ambas compilation results y
demostrar que la única diferencia de destino es schema-check -> shadow real.

## 10. Materializar contratos raw vacíos

Ejecutar individualmente, sin dependencias transitivas:

```text
market_price_raw
corporate_actions_pit
market_session_calendar
```

Verificar que las tres tablas existen exclusivamente en el shadow real y sus
schemas coinciden con los contratos machine-readable.

## 11. Plan acotado de backfill

Usar el último día completo anterior a la validación. Para la validación de
agosto de 2026, el scope aprobado es:

```text
START_DATE=2024-01-01
END_DATE=2026-08-13
INTRADAY_START_DATE=2026-06-16
HOURLY_START_DATE=2025-01-01
MAX_ROWS=100000
```

Incluye cinco acciones estadounidenses, BTC, ETH y USD/CLP, definidos en el
asset set versionado.

```bash
mkdir -p /tmp/wp04-shadow-evidence/backfill

python tools/wp04_shadow_backfill.py \
  --expected-git-sha "$FINAL_SHA" \
  --asset-set "$ASSET_SET" \
  --start-date "$START_DATE" \
  --end-date "$END_DATE" \
  --intraday-start-date "$INTRADAY_START_DATE" \
  --hourly-start-date "$HOURLY_START_DATE" \
  --max-rows "$MAX_ROWS" \
  --work-dir /tmp/wp04-shadow-evidence/backfill \
  --output /tmp/wp04-shadow-evidence/wp04_shadow_backfill_plan.json
```

Revisar:

- SHA y asset-set checksum;
- assets exactos;
- fechas y límites;
- Yahoo daily/15m/1h;
- Stooq daily para las cinco acciones;
- calendarios XNYS/FX/cripto;
- checksums y conteos de los tres JSONL;
- `production_change_allowed=false`.

## 12. Ejecución append-only e idempotencia

Primera ejecución:

```bash
python tools/wp04_shadow_backfill.py \
  --expected-git-sha "$FINAL_SHA" \
  --execute \
  --plan-file /tmp/wp04-shadow-evidence/wp04_shadow_backfill_plan.json \
  --expected-plan-checksum "$WP04_PLAN_CHECKSUM" \
  --acknowledge-shadow-write WP04_SHADOW_WRITE \
  --project-id "$PROJECT_ID" \
  --dataset-id "$REAL_SHADOW_DATASET" \
  --location "$LOCATION" \
  --environment shadow \
  --output /tmp/wp04-shadow-evidence/wp04_shadow_backfill_execution.json
```

Repetir exactamente con el mismo plan y guardar como
`wp04_shadow_backfill_idempotence.json`. La segunda ejecución debe insertar cero
revisiones y cero sesiones nuevas.

## 13. Materialización ordenada

Ejecutar individualmente, con `transitiveDependenciesIncluded=false`:

```text
price_source_reconciliation
market_price_canonical
fx_rates_pit
trading_price_features_canonical_shadow
trading_price_features_wp04_shadow
wp04_legacy_vs_canonical_shadow
audit_canonical_prices
```

Registrar invocation ID, target, state y destination. No ejecutar
`trading_price_features` operacional como target.

## 14. Evidencia final

```bash
python tools/wp04_shadow_evidence.py \
  --project-id "$PROJECT_ID" \
  --dataset-id "$REAL_SHADOW_DATASET" \
  --location "$LOCATION" \
  --environment shadow \
  --git-sha "$FINAL_SHA" \
  --ci-run-id "$CI_RUN_ID" \
  --output /tmp/wp04-shadow-evidence/wp04_shadow_evidence.json
```

Exigir:

```text
evaluation.status = PASS
hard_gate_count = 0
audit_canonical_prices.violation_count = 0
raw duplicate revisions = 0
canonical duplicate keys = 0
available_before_bar_end = 0
mixed daily/intraday selection = 0
invalid crypto 4h buckets = 0
unblocked material reconciliation problems = 0
blocked price consumption = 0
invalid USD/CLP rates = 0
bridge legacy source count = 0
promotion violations = 0
production-change violations = 0
```

Los historical corporate actions de Yahoo sin publication timestamp deben
seguir marcados `UNVERIFIED_AVAILABLE_AT`; no relajar ese gate para fabricar
cobertura PIT.

## 15. No mutación

Repetir inventarios before/after y demostrar:

- cero escrituras en `acciones_dataset` atribuibles a WP-04;
- Dataform production y `dataform-production` sin cambios;
- Cloud Run y schedulers sin cambios;
- sin Terraform apply, IAM, Secret Manager o broker;
- Strategy Brain permanece pausado y BACKTEST_ONLY;
- todas las escrituras WP-04 se limitaron a los dos datasets shadow.

## 16. Evidencia a comprometer

Después de ejecutar todas las herramientas que requieren checkout limpio,
volver a la rama WP-04 y comprometer únicamente artefactos sanitizados:

```text
docs/audit-grade/evidence/wp04_schema_graph_plan.json
docs/audit-grade/evidence/wp04_schema_graph_result.json
docs/audit-grade/evidence/wp04_shadow_backfill_plan.json
docs/audit-grade/evidence/wp04_shadow_backfill_execution.json
docs/audit-grade/evidence/wp04_shadow_backfill_idempotence.json
docs/audit-grade/evidence/wp04_shadow_evidence.json
docs/audit-grade/evidence/WP-04.md
docs/audit-grade/08_traceability_matrix.md
```

No comprometer tokens, cookies, credenciales, payloads completos de proveedor ni
información privada. Mantener la PR como draft y no cerrar Issue #39.

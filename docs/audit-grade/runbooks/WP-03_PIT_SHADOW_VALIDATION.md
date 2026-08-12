# WP-03 — Validación shadow de fundamentales y earnings PIT

## Propósito

Materializar y validar WP-03 en un dataset BigQuery **aislado**, sin alterar servicios, schedulers, tablas operativas, Strategy Brain, Paper Champion ni el broker.

La única escritura autorizada es un dataset cuyo nombre contenga `shadow` y cuyas etiquetas sean exactamente:

```text
environment=shadow
work_package=wp03
```

Las fuentes legacy que WP-03 necesita para construir el dual-run permanecen en el dataset operativo y se consumen en modo read-only. El dataset de lectura y el dataset de salida son límites distintos.

## Invariantes no negociables

- checkout limpio del SHA exacto aprobado;
- CI exitoso del mismo SHA;
- `Deploy Cloud Run service` permanece deshabilitado;
- Strategy Brain permanece `PAUSED` y `BACKTEST_ONLY`;
- champion/challenger permanece `SHADOW_ONLY`;
- Alpaca permanece Paper;
- no se ejecuta `terraform apply`;
- no se actualiza Dataform `production`;
- no se escribe en `acciones_dataset` ni en otro dataset operativo;
- las lecturas legacy autorizadas provienen únicamente de `acciones_dataset`;
- `vars.auditDataset` y `vars.operationalDataset` nunca pueden apuntar al mismo dataset durante la validación shadow;
- no se sintetiza `available_at` desde `filing_date` o `period_end_date`;
- ningún resultado legacy se vuelve promocionable.

## Variables

```bash
export FINAL_SHA=<SHA_EXACTO_REVISADO>
export CI_RUN_ID=<CI_RUN_DEL_SHA_EXACTO>
export PROJECT_ID=<PROYECTO_GCP>
export LOCATION=us-east1
export OPERATIONAL_DATASET=acciones_dataset
export SHADOW_DATASET=acciones_dataset_shadow_wp03
export SEC_USER_AGENT='firstlayer-stock-market/1.0 contacto@example.com'
export MAPPING_VERSION=sec-company-tickers-2026-08-11-v1
export WP03_MAX_ROWS=1000
export WP03_EVIDENCE_TMP=/tmp/wp03-shadow-evidence
mkdir -p "$WP03_EVIDENCE_TMP"
```

El correo de `SEC_USER_AGENT` debe ser un contacto real autorizado y no debe persistirse en el repositorio.

## 1. Checkout y verificación local

```bash
git fetch origin
git checkout --detach "$FINAL_SHA"
test "$(git rev-parse HEAD)" = "$FINAL_SHA"
test -z "$(git status --porcelain --untracked-files=all)"

python -m pip install --requirement requirements-ci.txt
python -m compileall -q tools scripts tests cloud-functions
python -m unittest discover -s tests -p 'test_*.py'
python scripts/ci/verify_repo_invariants.py
python scripts/ci/verify_action_pinning.py
python scripts/ci/validate_data_contracts.py \
  --repo-root . \
  --contracts-dir contracts \
  --manifest contracts/manifest.json \
  --runtime-manifest cloud-functions/strategy_brain/contract_set_manifest.json

git diff --check
(
  cd dataform
  npm ci
  npm exec -- dataform compile
)
```

Todos los comandos deben devolver `0`. No continuar si el SHA o el árbol de trabajo no coinciden.

## 2. Inventario GCP read-only

```bash
gcloud config get-value project
bq show --format=prettyjson "$PROJECT_ID:$SHADOW_DATASET" || true
bq show --format=prettyjson "$PROJECT_ID:$OPERATIONAL_DATASET"
gcloud run services list --project "$PROJECT_ID" --region "$LOCATION"
gcloud scheduler jobs list --project "$PROJECT_ID" --location "$LOCATION"
```

Guardar salidas sanitizadas fuera del checkout. No imprimir secretos.

Las únicas tablas operativas autorizadas como inputs read-only de WP-03 son:

```text
macro_earnings_calendar
trading_price_features
asset_profile
valuation_model_profile
trading_historical_context
portfolio_valuation_daily
legacy_result_registry
```

No materializar ni copiar estas tablas al dataset shadow como workaround.

## 3. Dataset aislado

Solo si no existe:

```bash
bq --location="$LOCATION" mk --dataset \
  --description='WP-03 isolated PIT shadow validation' \
  --label=environment:shadow \
  --label=work_package:wp03 \
  "$PROJECT_ID:$SHADOW_DATASET"

bq show --format=prettyjson "$PROJECT_ID:$SHADOW_DATASET"
```

Debe observarse `shadow` en el ID y ambas etiquetas exactas.

## 4. Compilación Dataform con separación input/output

La compilation result debe preservar dos destinos diferentes:

```text
defaultDatabase = $PROJECT_ID
defaultSchema = $OPERATIONAL_DATASET
vars.auditDataset = $SHADOW_DATASET
vars.operationalDataset = $OPERATIONAL_DATASET
vars.environment = shadow
vars.financialMappingVersion = $MAPPING_VERSION
```

Reglas obligatorias:

- NO sobrescribir `defaultSchema` con `$SHADOW_DATASET`;
- `vars.auditDataset` = `$SHADOW_DATASET`;
- `vars.operationalDataset` = `$OPERATIONAL_DATASET`;
- todos los outputs WP-03 usan explícitamente `vars.auditDataset`;
- `macro_earnings_calendar` se resuelve mediante `vars.operationalDataset`;
- los demás inputs legacy tienen schema explícito `acciones_dataset`;
- no actualizar `dataform-production`, release config `production` ni workflow config `production`.

Targets autorizados:

```text
financial_statements_pit_raw
financial_statements_pit
financial_quarters_pit
financial_ttm_pit
earnings_events_pit
trading_financial_context_pit
trading_earnings_context_pit
portfolio_valuation_pit_shadow
trading_historical_context_pit
wp03_legacy_vs_pit_shadow
wp03_legacy_invalidation
audit_no_lookahead
```

Antes de ejecutar, inspeccionar la compilation result y demostrar:

- cero compilation errors;
- cada **output** autorizado apunta a `$PROJECT_ID.$SHADOW_DATASET`;
- cada **lectura legacy** autorizada apunta a `$PROJECT_ID.$OPERATIONAL_DATASET`;
- ninguna sentencia DDL/DML escribe en `$PROJECT_ID.$OPERATIONAL_DATASET`;
- ninguna acción modifica Cloud Run, Scheduler, IAM o Secret Manager.

Guardar `compilation_result_id`, SHA, targets y tabla de inputs/outputs en `$WP03_EVIDENCE_TMP`.

No usar `transitiveDependenciesIncluded=true`. Las dependencias legacy se leen, no se ejecutan ni materializan durante esta validación.

## 5. Materializar solo la tabla raw

Ejecutar primero únicamente:

```text
financial_statements_pit_raw
```

Verificar que fue creada exactamente en:

```text
$PROJECT_ID.$SHADOW_DATASET.financial_statements_pit_raw
```

Comparar su schema con `contracts/financial_statements_pit_raw.yaml`. Debe existir cero schema drift.

## 6. Plan SEC sin escritura

```bash
python tools/wp03_shadow_backfill.py \
  --expected-git-sha "$FINAL_SHA" \
  --tickers AAPL,MSFT,NVDA,META,AMZN \
  --start-year 2022 \
  --end-year 2026 \
  --max-rows "$WP03_MAX_ROWS" \
  --mapping-version "$MAPPING_VERSION" \
  --environment shadow \
  --output "$WP03_EVIDENCE_TMP/wp03_shadow_backfill_plan.json"

export WP03_PLAN_CHECKSUM="$(python -c 'import json,sys; print(json.load(open(sys.argv[1]))["plan_checksum"])' "$WP03_EVIDENCE_TMP/wp03_shadow_backfill_plan.json")"
```

Revisar mapping version/checksum, tickers, rango, límite, conteos, razones de rechazo, `revision_set_sha256`, `plan_checksum` y `production_change_allowed=false`.

No ejecutar si aparecen tickers inesperados, una versión distinta, más filas que el límite o cero filas por error de fuente.

## 7. Backfill append-only vinculado al plan

```bash
python tools/wp03_shadow_backfill.py \
  --expected-git-sha "$FINAL_SHA" \
  --tickers AAPL,MSFT,NVDA,META,AMZN \
  --start-year 2022 \
  --end-year 2026 \
  --max-rows "$WP03_MAX_ROWS" \
  --mapping-version "$MAPPING_VERSION" \
  --environment shadow \
  --project-id "$PROJECT_ID" \
  --dataset-id "$SHADOW_DATASET" \
  --table-id financial_statements_pit_raw \
  --location "$LOCATION" \
  --execute \
  --expected-plan-checksum "$WP03_PLAN_CHECKSUM" \
  --acknowledge-shadow-write WP03_SHADOW_WRITE \
  --output "$WP03_EVIDENCE_TMP/wp03_shadow_backfill_execution.json"
```

La herramienta debe rechazar checkout sucio/SHA distinto, checksum distinto, dataset sin `shadow`, etiquetas incorrectas, schema distinto, otro table ID, más de 10 tickers, más de 10 años o más de 10.000 filas.

## 8. Materializar el resto del grafo

Después del backfill, ejecutar los targets restantes en orden de dependencia y sin dependencias transitivas:

1. `financial_statements_pit`
2. `financial_quarters_pit`
3. `financial_ttm_pit`
4. `earnings_events_pit`
5. `trading_financial_context_pit`
6. `trading_earnings_context_pit`
7. `portfolio_valuation_pit_shadow`
8. `trading_historical_context_pit`
9. `wp03_legacy_vs_pit_shadow`
10. `wp03_legacy_invalidation`
11. `audit_no_lookahead`

Después de cada grupo, comprobar destino, estado y ausencia de escritura operativa.

## 9. Evidencia automática read-only

```bash
python tools/wp03_shadow_evidence.py \
  --expected-git-sha "$FINAL_SHA" \
  --ci-run-id "$CI_RUN_ID" \
  --project-id "$PROJECT_ID" \
  --dataset-id "$SHADOW_DATASET" \
  --location "$LOCATION" \
  --environment shadow \
  --mapping-version "$MAPPING_VERSION" \
  --output "$WP03_EVIDENCE_TMP/wp03_shadow_evidence.json"
```

La herramienta exige checkout exacto y limpio, valida etiquetas, ubicación, tablas y schema raw, y devuelve exit code `0` solo si todos los hard gates pasan.

Criterios mínimos:

- `evaluation.status = PASS`;
- `hard_gate_count = 0`;
- `audit_no_lookahead.violation_count = 0`;
- revision IDs únicos;
- cero availability mismatch;
- cero TTM complete inválido;
- cero earnings retroactivo;
- cero múltiplo negativo o aritmética cross-currency;
- cero filas promocionables en comparación e invalidación.

No existe allowlist para una violación point-in-time.

## 10. Verificación de no mutación

Repetir el inventario inicial y demostrar:

- workflow de deploy sigue deshabilitado;
- Strategy Brain sigue pausado;
- Cloud Run y schedulers no cambiaron;
- no hubo Terraform apply;
- no hubo IAM/Secret Manager mutation;
- no hubo Dataform production update;
- no hubo broker call;
- no hubo escritura en `$OPERATIONAL_DATASET`;
- solo se escribió en `$SHADOW_DATASET`.

## 11. Evidencia documental

Después de terminar las operaciones que exigen checkout limpio, copiar los JSON desde `/tmp` al repositorio y registrar en `docs/audit-grade/evidence/WP-03.md`:

- SHA exacto y CI run;
- project/location/datasets de lectura y escritura;
- labels shadow;
- compilation result y targets;
- inputs operativos read-only;
- mapping version/checksum;
- checksum del plan;
- filas staged/inserted/eligible/rejected;
- checksum del conjunto de revisiones;
- checksum de evidencia;
- `audit_no_lookahead = 0`;
- divergencias legacy/PIT;
- confirmación de no deploy/no scheduler/no broker/no producción;
- comandos y exit codes.

Actualizar `docs/audit-grade/08_traceability_matrix.md` sin declarar `PASS` donde falte evidencia.

## 12. Limpieza

El store es append-only; no se borran revisiones individuales. Si el resultado es inválido, capturar inventario/checksums, marcar la ejecución `FAIL` y eliminar únicamente el dataset shadow aislado:

```bash
bq rm -r -f -d "$PROJECT_ID:$SHADOW_DATASET"
```

Nunca ejecutar este comando contra el dataset operativo.

## Stop conditions

Detenerse ante:

- SHA distinto o checkout sucio;
- `defaultSchema` resuelto al dataset shadow;
- `vars.operationalDataset` distinto de `$OPERATIONAL_DATASET`;
- output WP-03 fuera de `$SHADOW_DATASET`;
- DDL/DML contra `$OPERATIONAL_DATASET`;
- schema drift;
- una sola violación no-look-ahead;
- revision ID duplicado;
- etiquetas ausentes;
- intento de deploy;
- incertidumbre sobre el destino.

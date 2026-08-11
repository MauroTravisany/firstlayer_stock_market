# WP-03 — Validación shadow de fundamentales y earnings PIT

## Propósito

Materializar y validar WP-03 en un dataset BigQuery **aislado**, sin alterar servicios, schedulers, tablas operativas, Strategy Brain, Paper Champion ni el broker.

La única escritura autorizada es un dataset cuyo nombre contenga `shadow` y cuyas etiquetas sean exactamente:

```text
environment=shadow
work_package=wp03
```

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
- no se sintetiza `available_at` desde `filing_date` o `period_end_date`;
- ningún resultado legacy se vuelve promocionable.

## Variables

```bash
export FINAL_SHA=<SHA_EXACTO_REVISADO>
export CI_RUN_ID=<CI_RUN_DEL_SHA_EXACTO>
export PROJECT_ID=<PROYECTO_GCP>
export LOCATION=us-east1
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
bq show --format=prettyjson "$PROJECT_ID:acciones_dataset"
gcloud run services list --project "$PROJECT_ID" --region "$LOCATION"
gcloud scheduler jobs list --project "$PROJECT_ID" --location "$LOCATION"
```

Guardar salidas sanitizadas fuera del checkout. No imprimir secretos.

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

## 4. Materialización Dataform limitada

Compilar desde `FINAL_SHA` con overrides hacia `$SHADOW_DATASET`. No actualizar `dataform-production` ni el release `production`.

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
- database = `$PROJECT_ID`;
- schema = `$SHADOW_DATASET` para cada target WP-03;
- ningún target apunta al dataset operativo;
- no se modifica Cloud Run, Scheduler, IAM ni Secret Manager.

Guardar `compilation_result_id`, SHA y targets en `$WP03_EVIDENCE_TMP`.

## 5. Plan SEC sin escritura

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

El output se guarda en `/tmp` para mantener limpio el checkout. No ejecutar si aparecen tickers inesperados, una versión distinta, más filas que el límite o cero filas por error de fuente.

## 6. Backfill append-only vinculado al plan

La ejecución vuelve a consultar SEC y debe reconstruir exactamente el checksum aprobado. Cualquier cambio de inputs o fuente bloquea la escritura.

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

## 7. Evidencia automática read-only

Después de materializar todos los targets WP-03:

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

La herramienta solo ejecuta consultas `SELECT`/`WITH`, exige checkout exacto y limpio, valida etiquetas y ubicación, compara el schema raw con el contrato y devuelve exit code `0` solo si todos los hard gates pasan.

Controles incluidos:

- unicidad de `revision_id`;
- filas de la mapping version objetivo;
- disponibilidad y quality status canónicos;
- Q4 y lineage de componentes;
- TTM consecutivo y de una moneda;
- EXPECTED/REPORTED earnings;
- valoración sin múltiplos negativos ni aritmética cross-currency;
- `audit_no_lookahead = 0`;
- comparación legacy/PIT no promocionable;
- invalidación legacy completa.

## 8. Evidencia documental

Después de terminar las operaciones que exigen checkout limpio, copiar los JSON desde `/tmp` al repositorio y registrar en `docs/audit-grade/evidence/WP-03.md`:

- SHA exacto y CI run;
- project/location/dataset shadow y etiquetas;
- compilation result y targets;
- mapping version/checksum;
- checksum del plan;
- filas staged/inserted/eligible/rejected;
- checksum del conjunto de revisiones;
- checksum de evidencia;
- controles de integridad;
- `audit_no_lookahead = 0`;
- divergencias legacy/PIT;
- confirmación de no deploy/no scheduler/no broker/no producción;
- comandos y exit codes.

Actualizar `docs/audit-grade/08_traceability_matrix.md` sin declarar `PASS` donde falte evidencia.

## 9. Limpieza

El store es append-only; no se borran revisiones individuales. Si el resultado es inválido, capturar inventario/checksums, marcar la ejecución `FAIL` y eliminar únicamente el dataset shadow aislado:

```bash
bq rm -r -f -d "$PROJECT_ID:$SHADOW_DATASET"
```

Nunca ejecutar este comando contra el dataset operativo.

## Stop conditions

Detenerse ante SHA distinto, checkout sucio, checksum de plan distinto, target fuera de shadow, schema drift, una sola violación no-look-ahead, revision ID duplicado, etiquetas ausentes, intento de deploy o incertidumbre sobre el destino.

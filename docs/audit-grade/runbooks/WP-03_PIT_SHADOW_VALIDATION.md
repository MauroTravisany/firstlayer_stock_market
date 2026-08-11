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
export PROJECT_ID=<PROYECTO_GCP>
export LOCATION=us-east1
export SHADOW_DATASET=acciones_dataset_shadow_wp03
export SEC_USER_AGENT='firstlayer-stock-market/1.0 contacto@example.com'
export MAPPING_VERSION=sec-company-tickers-2026-08-11-v1
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
  --mapping-version "$MAPPING_VERSION" \
  --environment shadow \
  --output "$WP03_EVIDENCE_TMP/wp03_shadow_backfill_plan.json"
```

Revisar mapping version/checksum, tickers, rango, conteos, razones de rechazo, `revision_set_sha256` y `production_change_allowed=false`.

El output se guarda en `/tmp` para que el checkout permanezca limpio. No ejecutar si aparecen tickers inesperados, una versión distinta o cero filas debido a un error de fuente.

## 6. Backfill append-only

```bash
python tools/wp03_shadow_backfill.py \
  --expected-git-sha "$FINAL_SHA" \
  --tickers AAPL,MSFT,NVDA,META,AMZN \
  --start-year 2022 \
  --end-year 2026 \
  --mapping-version "$MAPPING_VERSION" \
  --environment shadow \
  --project-id "$PROJECT_ID" \
  --dataset-id "$SHADOW_DATASET" \
  --table-id financial_statements_pit_raw \
  --location "$LOCATION" \
  --execute \
  --acknowledge-shadow-write WP03_SHADOW_WRITE \
  --output "$WP03_EVIDENCE_TMP/wp03_shadow_backfill_execution.json"
```

La herramienta debe rechazar checkout sucio/SHA distinto, dataset sin `shadow`, etiquetas incorrectas, schema distinto, otro table ID, más de 10 tickers o más de 10 años.

## 7. Integridad y no-look-ahead

```sql
SELECT COUNT(*) AS rows,
       COUNT(DISTINCT revision_id) AS unique_revisions,
       COUNTIF(backtest_eligible) AS eligible_rows,
       COUNTIF(NOT backtest_eligible) AS rejected_rows
FROM `<PROJECT>.<SHADOW_DATASET>.financial_statements_pit_raw`;
```

Debe cumplirse `rows = unique_revisions`.

```sql
SELECT ticker, fiscal_year, fiscal_quarter,
       COUNT(*) AS observed_revisions,
       MIN(available_at) AS first_available_at,
       MAX(available_at) AS latest_available_at
FROM `<PROJECT>.<SHADOW_DATASET>.financial_statements_pit`
GROUP BY ticker, fiscal_year, fiscal_quarter
ORDER BY ticker, fiscal_year, fiscal_quarter;
```

Confirmar que amendments/restatements no eliminan revisiones anteriores.

```sql
SELECT eligibility_reason, quality_status, COUNT(*) AS rows
FROM `<PROJECT>.<SHADOW_DATASET>.financial_statements_pit_raw`
GROUP BY eligibility_reason, quality_status
ORDER BY rows DESC;
```

Ejecutar el assertion/modelo y consultar:

```sql
SELECT *
FROM `<PROJECT>.<SHADOW_DATASET>.audit_no_lookahead`;
```

Criterio obligatorio: `row_count = 0`. No existe allowlist.

## 8. Dual-run legacy/PIT

```sql
SELECT pit_divergence_type, COUNT(*) AS rows
FROM `<PROJECT>.<SHADOW_DATASET>.wp03_legacy_vs_pit_shadow`
GROUP BY pit_divergence_type
ORDER BY rows DESC;
```

```sql
SELECT COUNTIF(promotion_eligible) AS promotion_eligible_rows
FROM `<PROJECT>.<SHADOW_DATASET>.wp03_legacy_vs_pit_shadow`;
```

`promotion_eligible_rows` debe ser `0`. La divergencia es diagnóstica, no una promoción.

## 9. Evidencia

Después de finalizar todas las operaciones que exigen checkout limpio, copiar la evidencia desde `/tmp` al repositorio y registrar en `docs/audit-grade/evidence/WP-03.md`:

- SHA exacto y CI run;
- project/location/dataset shadow y etiquetas;
- compilation result y targets;
- mapping version/checksum;
- plan/ejecución bounded;
- filas staged/inserted/eligible/rejected;
- checksum del conjunto de revisiones;
- controles de integridad;
- `audit_no_lookahead = 0`;
- divergencias legacy/PIT;
- confirmación de no deploy/no scheduler/no broker/no producción;
- comandos y exit codes.

Actualizar `docs/audit-grade/08_traceability_matrix.md` sin declarar `PASS` donde falte evidencia.

## 10. Limpieza

El store es append-only; no se borran revisiones individuales. Si el resultado es inválido, capturar inventario/checksums, marcar la ejecución `FAIL` y eliminar únicamente el dataset shadow aislado:

```bash
bq rm -r -f -d "$PROJECT_ID:$SHADOW_DATASET"
```

Nunca ejecutar este comando contra el dataset operativo.

## Stop conditions

Detenerse ante SHA distinto, checkout sucio, target fuera de shadow, schema drift, una sola violación no-look-ahead, revision ID duplicado, etiquetas ausentes, intento de deploy o incertidumbre sobre el destino.

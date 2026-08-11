# WP-03 — Validación shadow de fundamentales y earnings PIT

## Propósito

Materializar y validar la implementación de WP-03 en un dataset BigQuery **aislado**, sin alterar servicios, schedulers, tablas operativas, Strategy Brain, Paper Champion ni el broker.

Este runbook no autoriza despliegue. Su única escritura permitida es en un dataset dedicado cuyo nombre contenga `shadow` y cuyas etiquetas sean:

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
- no se actualiza el release Dataform `production`;
- no se escribe en `acciones_dataset` ni en otro dataset operativo;
- no se sintetiza `available_at` desde `filing_date` o `period_end_date`;
- un resultado legacy no se vuelve promocionable.

## Variables de la sesión

```bash
export REPO=MauroTravisany/firstlayer_stock_market
export FINAL_SHA=<SHA_EXACTO_REVISADO>
export PROJECT_ID=<PROYECTO_GCP>
export LOCATION=us-east1
export SHADOW_DATASET=acciones_dataset_shadow_wp03
export SEC_USER_AGENT='firstlayer-stock-market/1.0 contacto@example.com'
export MAPPING_VERSION=sec-company-tickers-2026-08-11-v1
```

El correo de `SEC_USER_AGENT` debe ser un contacto real autorizado. No debe almacenarse como secreto en el repositorio.

## 1. Verificar el checkout

```bash
git fetch origin
git checkout --detach "$FINAL_SHA"
test "$(git rev-parse HEAD)" = "$FINAL_SHA"
test -z "$(git status --porcelain --untracked-files=all)"
```

No continuar si el SHA o el árbol de trabajo no coinciden.

## 2. Verificación local completa

```bash
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

Todos los comandos deben devolver `0`.

## 3. Inspección read-only de GCP

Antes de crear recursos:

```bash
gcloud config get-value project
bq show --format=prettyjson "$PROJECT_ID:$SHADOW_DATASET" || true
bq show --format=prettyjson "$PROJECT_ID:acciones_dataset"
gcloud run services list --project "$PROJECT_ID" --region "$LOCATION"
gcloud scheduler jobs list --project "$PROJECT_ID" --location "$LOCATION"
```

Guardar la salida sanitizada. No imprimir secretos ni variables sensibles.

## 4. Crear el dataset aislado

Solo si no existe:

```bash
bq --location="$LOCATION" mk --dataset \
  --description='WP-03 isolated PIT shadow validation' \
  --label=environment:shadow \
  --label=work_package:wp03 \
  "$PROJECT_ID:$SHADOW_DATASET"
```

Verificar inmediatamente:

```bash
bq show --format=prettyjson "$PROJECT_ID:$SHADOW_DATASET"
```

Debe observarse el nombre `shadow` y ambas etiquetas exactas.

## 5. Materializar únicamente el grafo WP-03 en shadow

Compilar Dataform desde `FINAL_SHA` con overrides que apunten al dataset aislado. No actualizar `dataform-production` ni el release `production`.

El grafo autorizado incluye solamente:

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
- schema/dataset = `$SHADOW_DATASET` para todas las acciones WP-03;
- ninguna acción apunta al dataset operativo;
- ninguna acción modifica Cloud Run, Scheduler, IAM o Secret Manager.

Guardar `compilation_result_id`, SHA y lista de targets.

## 6. Plan de backfill SEC sin escritura

Ejemplo bounded inicial:

```bash
python tools/wp03_shadow_backfill.py \
  --expected-git-sha "$FINAL_SHA" \
  --tickers AAPL,MSFT,NVDA,META,AMZN \
  --start-year 2022 \
  --end-year 2026 \
  --mapping-version "$MAPPING_VERSION" \
  --environment shadow \
  --output docs/audit-grade/evidence/wp03_shadow_backfill_plan.json
```

Revisar:

- mapping version y SHA-256;
- tickers y rango;
- conteo total y elegible;
- razones de rechazo;
- `revision_set_sha256`;
- `production_change_allowed=false`.

No ejecutar si el plan contiene un ticker inesperado, cero filas por un error de fuente o una versión de mapping distinta.

## 7. Backfill append-only autorizado

Solo después de aprobar el plan:

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
  --output docs/audit-grade/evidence/wp03_shadow_backfill_execution.json
```

La herramienta debe negarse a ejecutar si:

- el checkout está sucio o el SHA no coincide;
- el dataset no contiene `shadow`;
- faltan las etiquetas requeridas;
- el schema raw no coincide exactamente;
- se intenta otro table ID;
- el rango supera 10 años o la lista supera 10 tickers.

## 8. Controles de integridad

Ejecutar consultas read-only y guardar resultados:

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

## 9. Audit no-look-ahead

Ejecutar el assertion/modelo `audit_no_lookahead` y además consultar:

```sql
SELECT *
FROM `<PROJECT>.<SHADOW_DATASET>.audit_no_lookahead`;
```

Criterio obligatorio:

```text
row_count = 0
```

Cualquier fila es `FAIL`; no se admite allowlist.

## 10. Dual-run legacy vs PIT

Consultar y exportar:

```sql
SELECT pit_divergence_type, COUNT(*) AS rows
FROM `<PROJECT>.<SHADOW_DATASET>.wp03_legacy_vs_pit_shadow`
GROUP BY pit_divergence_type
ORDER BY rows DESC;
```

La divergencia es evidencia diagnóstica. Nunca implica promoción automática.

También verificar:

```sql
SELECT COUNTIF(promotion_eligible) AS promotion_eligible_rows
FROM `<PROJECT>.<SHADOW_DATASET>.wp03_legacy_vs_pit_shadow`;
```

Debe devolver `0`.

## 11. Evidencia mínima

Registrar en `docs/audit-grade/evidence/WP-03.md`:

- SHA exacto;
- CI run y jobs;
- project/location/dataset shadow;
- etiquetas del dataset;
- Dataform compilation result y targets;
- mapping version y checksum;
- plan y ejecución del backfill;
- filas staged/inserted/rejected;
- checksum del conjunto de revisiones;
- resultados de integridad;
- `audit_no_lookahead` con cero filas;
- distribución de divergencias legacy/PIT;
- confirmación de no deploy/no scheduler/no broker/no producción;
- todos los comandos y exit codes.

Actualizar también `docs/audit-grade/08_traceability_matrix.md` sin declarar `PASS` donde falte evidencia.

## 12. Limpieza y rollback

No existe rollback destructivo de revisiones individuales: el store es append-only. Si el backfill resulta inválido, marcar el dataset completo como rechazado en la evidencia y eliminar **solo el dataset shadow aislado**, después de capturar inventario y checksums:

```bash
bq rm -r -f -d "$PROJECT_ID:$SHADOW_DATASET"
```

Nunca ejecutar este comando contra el dataset operativo.

## Stop conditions

Detenerse inmediatamente ante:

- SHA distinto o checkout sucio;
- compilation target fuera del dataset shadow;
- schema drift;
- `audit_no_lookahead` con una o más filas;
- revisión duplicada por `revision_id`;
- falta de etiquetas;
- intento de deploy o cambio operacional;
- cualquier incertidumbre sobre el dataset destino.

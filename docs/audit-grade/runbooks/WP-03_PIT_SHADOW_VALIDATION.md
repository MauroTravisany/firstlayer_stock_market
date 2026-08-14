# WP-03 — Validación shadow de fundamentales y earnings PIT

## Propósito

Materializar y validar WP-03 en un dataset BigQuery aislado, sin alterar
servicios, schedulers, tablas operativas, Strategy Brain, Paper Champion ni el
broker.

La única escritura BigQuery autorizada es un dataset cuyo nombre contenga
`shadow` y cuyas etiquetas sean exactamente:

```text
environment=shadow
work_package=wp03
```

## Arquitectura de inputs y outputs

WP-03 mantiene tres clases de objeto distintas:

| Clase | Acceso | Dataset/resolución |
|---|---|---|
| Outputs WP-03 | WRITE limitado | `vars.auditDataset = $SHADOW_DATASET` |
| Fuentes legacy operativas | READ_ONLY | `vars.operationalDataset = acciones_dataset` o schema explícito `acciones_dataset` |
| Registro legacy congelado | REPOSITORY_STATIC | embebido en `wp03_legacy_invalidation.sqlx` desde la evidencia WP-00 |

Las seis dependencias BigQuery live autorizadas son:

```text
macro_earnings_calendar
trading_price_features
asset_profile
valuation_model_profile
trading_historical_context
portfolio_valuation_daily
```

`legacy_result_registry` no es una dependencia live. Su subconjunto afectado
está congelado dentro de `wp03_legacy_invalidation.sqlx`, con los mismos
`result_family`, `source_table` y `results_checksum` del registro WP-00. Esto
evita depender de una tabla operativa que puede no haber sido materializada.

## Invariantes no negociables

- checkout limpio del SHA exacto aprobado;
- CI exitoso del mismo SHA;
- `Deploy Cloud Run service` permanece deshabilitado;
- Strategy Brain permanece `PAUSED` y `BACKTEST_ONLY`;
- champion/challenger permanece `SHADOW_ONLY`;
- Alpaca permanece Paper;
- no se ejecuta `terraform apply`;
- no se actualiza Dataform `production`;
- no se mueve `dataform-production`;
- no se escribe en `acciones_dataset`;
- las lecturas legacy autorizadas provienen solo de `acciones_dataset`;
- `vars.auditDataset` y `vars.operationalDataset` son distintos;
- no se ejecutan dependencias legacy como targets;
- no se sintetiza `available_at` desde `filing_date` o `period_end_date`;
- ningún resultado legacy se vuelve promocionable.

## Variables

```bash
export FINAL_SHA=<SHA_EXACTO_REVISADO>
export CI_RUN_ID=<CI_RUN_DEL_SHA_EXACTO>
export PROJECT_ID=stocks-437902
export LOCATION=us-east1
export OPERATIONAL_DATASET=acciones_dataset
export SHADOW_DATASET=acciones_dataset_shadow_wp03
export DATAFORM_REPOSITORY=portfolio-valuation
export SEC_USER_AGENT='firstlayer-stock-market/1.0 contacto-real@example.com'
export MAPPING_VERSION=sec-company-tickers-2026-08-11-v1
export WP03_MAX_ROWS=1000
export WP03_EVIDENCE_TMP=/tmp/wp03-shadow-evidence
mkdir -p "$WP03_EVIDENCE_TMP"
```

El contacto de `SEC_USER_AGENT` debe ser real y autorizado. No persistirlo en
el repositorio, logs o artefactos.

## 1. Checkout exacto y gates locales

```bash
git fetch origin
git checkout --detach "$FINAL_SHA"
test "$(git rev-parse HEAD)" = "$FINAL_SHA"
test -z "$(git status --porcelain --untracked-files=all)"

python -m pip install --requirement requirements-ci.txt
python -m pip install --requirement cloud-functions/financial_data/requirements.txt

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

## 2. Inventario operacional read-only

Guardar salidas sanitizadas fuera del checkout:

```bash
gcloud config get-value project
bq show --format=prettyjson "$PROJECT_ID:$OPERATIONAL_DATASET"
bq show --format=prettyjson "$PROJECT_ID:$SHADOW_DATASET" || true
gcloud run services list --project "$PROJECT_ID" --region "$LOCATION"
gcloud scheduler jobs list --project "$PROJECT_ID" --location "$LOCATION"
```

Confirmar antes de cualquier escritura:

- `strategy-brain-generate = PAUSED`;
- `strategy-brain-review = PAUSED`;
- executor en Paper;
- workflow Cloud Run deshabilitado;
- ningún deploy o workflow de producción en curso.

## 3. Dataset shadow

Si no existe:

```bash
bq --location="$LOCATION" mk --dataset \
  --description='WP-03 isolated PIT shadow validation' \
  --label=environment:shadow \
  --label=work_package:wp03 \
  "$PROJECT_ID:$SHADOW_DATASET"
```

Si existe, solo reutilizarlo cuando nombre, location, labels y tablas existentes
tengan lineage WP-03 verificable. No borrar ni modificar un dataset incierto.

## 4. Preflight agregado de todas las dependencias

Ejecutar antes de crear compilation result o workflow invocation:

```bash
python tools/wp03_shadow_preflight.py \
  --expected-git-sha "$FINAL_SHA" \
  --project-id "$PROJECT_ID" \
  --operational-dataset "$OPERATIONAL_DATASET" \
  --shadow-dataset "$SHADOW_DATASET" \
  --location "$LOCATION" \
  --environment shadow \
  --output "$WP03_EVIDENCE_TMP/wp03_shadow_preflight.json"
```

Exigir:

```text
status = PASS
problems = []
production_change_allowed = false
```

La herramienta verifica en una sola ejecución:

- existencia de las seis fuentes operativas;
- todas las columnas realmente consumidas por el grafo WP-03;
- tipos de objeto BigQuery permitidos;
- location del dataset operativo;
- nombre, location y labels del dataset shadow;
- ausencia de tablas shadow inesperadas;
- que `wp03_legacy_invalidation` no vuelva a referenciar
  `legacy_result_registry`;
- que las diez filas afectadas y sus checksums coincidan con el registro
  congelado del repositorio.

No continuar corrigiendo tablas una por una. Si el preflight falla, guardar el
JSON completo y reportar todas las dependencias inválidas juntas.

## 5. Empaquetado Dataform exacto del subárbol

El repositorio Dataform conectado espera `package.json` en su raíz, mientras
que este repositorio guarda el proyecto bajo `dataform/`. Por ello no se debe
compilar directamente la raíz del PR ni mover archivos manualmente.

Crear una referencia candidata cuyo árbol sea exactamente el subárbol
`$FINAL_SHA:dataform`, usando el patrón transaccional ya probado por WP-01:

```bash
export DATAFORM_TREE_SHA="$(git rev-parse "$FINAL_SHA:dataform")"
export PREVIOUS_DATAFORM_PRODUCTION_SHA="$(
  git ls-remote --refs origin refs/heads/dataform-production | cut -f1
)"
export DATAFORM_CANDIDATE_BRANCH="dataform-wp03-shadow-${FINAL_SHA:0:12}"
export DATAFORM_CANDIDATE_REF="refs/heads/$DATAFORM_CANDIDATE_BRANCH"

git fetch --no-tags origin "$PREVIOUS_DATAFORM_PRODUCTION_SHA"
export DATAFORM_SNAPSHOT_COMMIT="$(
  printf 'WP-03 shadow Dataform snapshot for %s\n' "$FINAL_SHA" |
    git commit-tree "$DATAFORM_TREE_SHA" \
      -p "$PREVIOUS_DATAFORM_PRODUCTION_SHA"
)"
```

Crear la candidate ref con compare-and-swap/fail-closed. No mover
`dataform-production`. Guardar:

```text
FINAL_SHA
DATAFORM_TREE_SHA
DATAFORM_SNAPSHOT_COMMIT
DATAFORM_CANDIDATE_BRANCH
PREVIOUS_DATAFORM_PRODUCTION_SHA
```

Verificar que la raíz candidata contiene:

```text
package.json
package-lock.json
workflow_settings.yaml
definitions/
```

## 6. Compilation result con separación input/output

Crear una compilation result nueva desde `DATAFORM_CANDIDATE_BRANCH` con:

```text
defaultDatabase = $PROJECT_ID
defaultSchema = $OPERATIONAL_DATASET
vars.auditDataset = $SHADOW_DATASET
vars.operationalDataset = $OPERATIONAL_DATASET
vars.environment = shadow
vars.financialMappingVersion = $MAPPING_VERSION
```

Reglas:

- NO sobrescribir `defaultSchema` con `$SHADOW_DATASET`;
- NO reutilizar compilation results de otro SHA;
- NO actualizar release config `production`;
- NO mover `dataform-production`;
- NO usar `transitiveDependenciesIncluded=true`.

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

Inspeccionar la compilation result y construir una tabla:

```text
OBJECT | ROLE | DATABASE | DATASET | ACCESS | STATUS
```

Debe demostrar:

- los doce outputs escriben en `$PROJECT_ID.$SHADOW_DATASET`;
- las seis fuentes operativas se leen desde
  `$PROJECT_ID.$OPERATIONAL_DATASET`;
- `wp03_legacy_invalidation` no tiene dependencia BigQuery externa;
- ninguna sentencia DDL/DML escribe en `$OPERATIONAL_DATASET`;
- cero compilation errors;
- `resolvedGitCommitSha = DATAFORM_SNAPSHOT_COMMIT`.

## 7. Materializar tabla raw

Ejecutar únicamente:

```text
financial_statements_pit_raw
```

sin dependencias transitivas. Comparar su schema exacto con
`contracts/financial_statements_pit_raw.yaml`.

## 8. Plan SEC bounded

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

export WP03_PLAN_CHECKSUM="$(
  python -c \
    'import json,sys; print(json.load(open(sys.argv[1]))["plan_checksum"])' \
    "$WP03_EVIDENCE_TMP/wp03_shadow_backfill_plan.json"
)"
```

Exigir filas no vacías, checksum de mapping, checksum de revisiones,
`production_change_allowed=false` y scope exacto.

## 9. Backfill append-only ligado al plan

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

Verificar:

```text
COUNT(*) = COUNT(DISTINCT revision_id)
```

Una repetición idéntica debe ser idempotente.

## 10. Materialización ordenada

Ejecutar individualmente, sin dependencias transitivas:

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

Después de cada target, registrar destination, invocation ID, estado y
assertions. No ignorar fallos.

## 11. Evidencia automática

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

Exigir:

```text
exit code = 0
evaluation.status = PASS
hard_gate_count = 0
audit_no_lookahead.violation_count = 0
```

No existen allowlists point-in-time.

## 12. Verificación de no mutación

Repetir el inventario inicial y demostrar:

- Cloud Run sin cambios;
- schedulers sin cambios;
- Strategy Brain pausado;
- Dataform production sin cambios;
- `dataform-production` sin cambios;
- ningún Terraform apply;
- ningún IAM/Secret Manager mutation;
- ningún broker call;
- cero escrituras en `acciones_dataset`;
- escrituras únicamente en `$SHADOW_DATASET`.

## 13. Evidencia a conservar

Copiar al PR, sin secretos:

```text
wp03_shadow_preflight.json
wp03_shadow_backfill_plan.json
wp03_shadow_backfill_execution.json
wp03_shadow_evidence.json
compilation result sanitizada
workflow invocation IDs
inventario before/after
candidate branch/tree/snapshot metadata
```

Actualizar `docs/audit-grade/evidence/WP-03.md` y
`docs/audit-grade/08_traceability_matrix.md` según evidencia real.

## Stop conditions

Detenerse ante:

- SHA o CI distintos;
- checkout sucio;
- preflight distinto de PASS;
- cualquiera de las seis fuentes ausente o sin columnas requeridas;
- dependencia live hacia `legacy_result_registry`;
- output fuera de shadow;
- lectura legacy fuera del dataset operativo;
- compilation result de otro tree/SHA;
- schema drift;
- checksum de plan distinto;
- una violación no-look-ahead;
- revision ID duplicado;
- intento de deploy o mutación productiva.

No hacer merge, no cerrar #38 y no avanzar a WP-04 hasta revisión
independiente.

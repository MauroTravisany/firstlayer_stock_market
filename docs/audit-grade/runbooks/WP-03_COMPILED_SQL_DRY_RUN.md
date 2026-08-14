# WP-03 — Preflight semántico del grafo SQL compilado

## Propósito

Validar **todos** los `SELECT` y assertions compilados de WP-03 contra el
analizador real de GoogleSQL/BigQuery antes de materializar el grafo en el
dataset shadow de evidencia.

Este gate existe porque:

- `dataform compile` valida el grafo y genera SQL, pero no resuelve por sí solo
  todos los errores semánticos que dependen del catálogo BigQuery;
- un dry-run aislado de un modelo descendiente falla si sus tablas upstream
  todavía no existen;
- un dry-run de un script con DDL valida solamente el primer DDL y omite las
  sentencias posteriores;
- `CREATE TEMP TABLE` no está soportado por el dry-run de scripts.

Por eso WP-03 usa un **dataset schema-check desechable**, separado tanto del
dataset operativo como del dataset shadow de evidencia. El preflight crea:

1. una tabla raw vacía a partir del contrato versionado;
2. vistas lógicas con `WHERE FALSE`, en orden topológico, para conservar el
   schema de cada modelo sin materializar filas;
3. dry-runs de todas las assertions cuando sus dependencias ya existen.

La herramienta agrega todos los errores de ramas independientes y marca como
bloqueados únicamente los descendientes de un nodo fallido. No se detiene en el
primer error.

## Límites de seguridad

El preflight puede escribir metadatos únicamente en un dataset cuyo nombre
contenga simultáneamente `shadow` y `schema`, y que tenga exactamente estas
labels:

```text
environment=shadow
work_package=wp03
purpose=compiled_sql_validation
```

El dataset debe estar vacío. La herramienta nunca:

- escribe en `acciones_dataset`;
- escribe en el dataset shadow real de evidencia;
- ejecuta una `workflowInvocation`;
- ejecuta el backfill SEC;
- despliega Cloud Run;
- cambia schedulers, IAM, Secret Manager o Terraform;
- llama un broker;
- permite cambios productivos.

Cada resultado conserva:

```text
validation_dataset_only = true
production_change_allowed = false
```

## Acciones obligatorias

El inventario debe contener exactamente una vez cada output:

1. `financial_statements_pit_raw`
2. `financial_statements_pit`
3. `financial_quarters_pit`
4. `financial_ttm_pit`
5. `earnings_events_pit`
6. `trading_financial_context_pit`
7. `trading_earnings_context_pit`
8. `portfolio_valuation_pit_shadow`
9. `trading_historical_context_pit`
10. `wp03_legacy_vs_pit_shadow`
11. `wp03_legacy_invalidation`
12. `audit_no_lookahead`

También deben incluirse todas las assertions cuyo `parentAction` o dependencia
sea uno de esos outputs.

## 1. Checkout exacto

```bash
FINAL_SHA=<SHA_APROBADO>
CI_RUN_ID=<CI_APROBADO>

 git fetch origin
 git checkout --detach "$FINAL_SHA"
 test "$(git rev-parse HEAD)" = "$FINAL_SHA"
 test -z "$(git status --porcelain --untracked-files=all)"
```

Ejecutar antes los gates locales y Dataform compile definidos en el runbook
principal.

## 2. Variables

```bash
PROJECT_ID=stocks-437902
LOCATION=us-east1
OPERATIONAL_DATASET=acciones_dataset
REAL_SHADOW_DATASET=<DATASET_SHADOW_DE_EVIDENCIA>
VALIDATION_DATASET="acciones_dataset_shadow_wp03_schema_$(date -u +%Y%m%dT%H%M%SZ)"
WP03_EVIDENCE_TMP=/tmp/wp03-shadow-evidence
mkdir -p "$WP03_EVIDENCE_TMP"
```

`VALIDATION_DATASET` y `REAL_SHADOW_DATASET` deben ser distintos.

## 3. Crear el dataset schema-check

Esta es la única creación previa permitida para este gate:

```bash
bq \
  --project_id="$PROJECT_ID" \
  --location="$LOCATION" \
  mk \
  --dataset \
  --description="Disposable WP-03 compiled SQL schema validation" \
  --label=environment:shadow \
  --label=work_package:wp03 \
  --label=purpose:compiled_sql_validation \
  --default_table_expiration=86400 \
  "$PROJECT_ID:$VALIDATION_DATASET"
```

Verificar por lectura:

- location `us-east1`;
- las tres labels exactas;
- cero tablas y vistas;
- no es `acciones_dataset`;
- no es `REAL_SHADOW_DATASET`.

Si el nombre ya existe o contiene objetos, no reutilizarlo ni borrarlo. Crear
otro con un sufijo UTC nuevo.

## 4. Compilation result exclusiva para schema-check

No reutilizar compilation results anteriores. Crear una nueva desde el mismo
snapshot Dataform correspondiente a `FINAL_SHA` con:

```text
defaultDatabase = stocks-437902
defaultSchema = acciones_dataset
defaultLocation = us-east1
assertionSchema = VALIDATION_DATASET

vars.auditDataset = VALIDATION_DATASET
vars.operationalDataset = acciones_dataset
vars.environment = shadow
vars.financialMappingVersion = sec-company-tickers-2026-08-11-v1
```

Denominar el recurso completo:

```bash
SCHEMA_COMPILATION_RESULT="projects/.../compilationResults/..."
```

Comprobar:

- cero `compilationErrors`;
- todos los outputs y assertions apuntan a `VALIDATION_DATASET`;
- las seis fuentes legacy autorizadas son read-only desde
  `acciones_dataset`;
- `wp03_legacy_invalidation` no posee dependencia BigQuery externa;
- no existe ningún target de escritura fuera de `VALIDATION_DATASET`.

Esta compilation result no se usa para materializar el dataset shadow real.

## 5. Exportar todas las CompilationResultActions

La API oficial es paginada. No asumir que la primera respuesta contiene todo.
El siguiente script no imprime el token:

```bash
export SCHEMA_COMPILATION_RESULT
export WP03_EVIDENCE_TMP

python - <<'PY'
import json
import os
import subprocess
from pathlib import Path

import requests

name = os.environ["SCHEMA_COMPILATION_RESULT"]
out = Path(os.environ["WP03_EVIDENCE_TMP"]) / "wp03_schema_compilation_actions.json"
token = subprocess.check_output(
    ["gcloud", "auth", "print-access-token"], text=True
).strip()
url = f"https://dataform.googleapis.com/v1/{name}:query"
headers = {"Authorization": f"Bearer {token}"}
pages = []
page_token = None
while True:
    params = {"pageSize": 1000}
    if page_token:
        params["pageToken"] = page_token
    response = requests.get(url, headers=headers, params=params, timeout=60)
    response.raise_for_status()
    page = response.json()
    pages.append(page)
    page_token = page.get("nextPageToken")
    if not page_token:
        break
out.write_text(json.dumps({"pages": pages}, indent=2, sort_keys=True) + "\n")
print(out)
PY
```

El JSON se conserva sanitizado; no contiene el access token.

## 6. Crear el plan fail-closed

```bash
python tools/wp03_compiled_sql_semantic_preflight.py \
  --actions-json "$WP03_EVIDENCE_TMP/wp03_schema_compilation_actions.json" \
  --expected-git-sha "$FINAL_SHA" \
  --compilation-result "$SCHEMA_COMPILATION_RESULT" \
  --project-id "$PROJECT_ID" \
  --operational-dataset "$OPERATIONAL_DATASET" \
  --validation-dataset "$VALIDATION_DATASET" \
  --location "$LOCATION" \
  --environment shadow \
  --output "$WP03_EVIDENCE_TMP/wp03_schema_graph_plan.json"
```

El plan debe demostrar:

```text
operation = WP03_COMPILED_SQL_SCHEMA_GRAPH
mode = PLAN
required_output_count = 12
production_change_allowed = false
plan_checksum = <SHA256>
```

Además debe mostrar el orden topológico, el checksum de cada SQL y solo las
seis dependencias operativas autorizadas.

Revisar manualmente el plan. Extraer el checksum:

```bash
WP03_SCHEMA_PLAN_CHECKSUM="$(python - "$WP03_EVIDENCE_TMP/wp03_schema_graph_plan.json" <<'PY'
import json
import sys
print(json.load(open(sys.argv[1], encoding="utf-8"))["plan_checksum"])
PY
)"
```

No ejecutar si cualquier target, dependencia, checksum o dataset es inesperado.

## 7. Ejecutar el schema graph

Instalar `google-cloud-bigquery` en el entorno virtual aislado si todavía no
está presente. Luego:

```bash
python tools/wp03_compiled_sql_semantic_preflight.py \
  --actions-json "$WP03_EVIDENCE_TMP/wp03_schema_compilation_actions.json" \
  --expected-git-sha "$FINAL_SHA" \
  --compilation-result "$SCHEMA_COMPILATION_RESULT" \
  --project-id "$PROJECT_ID" \
  --operational-dataset "$OPERATIONAL_DATASET" \
  --validation-dataset "$VALIDATION_DATASET" \
  --location "$LOCATION" \
  --environment shadow \
  --execute \
  --expected-plan-checksum "$WP03_SCHEMA_PLAN_CHECKSUM" \
  --acknowledge-validation-write WP03_SCHEMA_VALIDATION_WRITE \
  --output "$WP03_EVIDENCE_TMP/wp03_schema_graph_result.json"
```

La herramienta:

1. verifica SHA y checkout limpio;
2. vuelve a construir y verificar el plan;
3. exige dataset vacío, location y labels exactas;
4. crea una tabla raw vacía desde
   `contracts/financial_statements_pit_raw.yaml`;
5. dry-runea cada `relation.selectQuery` con `dryRun=true` y
   `useLegacySql=false`;
6. crea una vista con `WHERE FALSE` únicamente cuando el dry-run pasa;
7. continúa validando ramas independientes;
8. bloquea descendientes de un nodo fallido;
9. dry-runea todas las assertions disponibles;
10. agrega todos los errores en un solo documento.

Las vistas schema-check no materializan filas y no escriben datos derivados.

## 8. Gate obligatorio

No crear ninguna `workflowInvocation` del dataset shadow real salvo que:

```text
exit code = 0
status = ALL_COMPILED_ACTIONS_SCHEMA_GRAPH_PASS
failed_action_count = 0
failed_assertion_count = 0
required_output_count = 12
validation_dataset_only = true
production_change_allowed = false
```

También se exige:

- una tabla `EMPTY_CONTRACT_TABLE`;
- once objetos `ZERO_ROW_SCHEMA_VIEW`;
- `zero_row_guard=true` para cada vista;
- todos los action results `PASS`;
- todos los assertion results `PASS`.

Un éxito de dry-run es evidencia semántica importante, pero no garantiza por sí
solo que una ejecución con datos termine correctamente. La materialización,
assertions de contenido, `audit_no_lookahead` e idempotencia siguen siendo
gates separados.

## 9. Recompilar para el dataset shadow real

Después de un schema graph PASS, crear **otra** compilation result desde el
mismo snapshot Dataform y el mismo `FINAL_SHA`, cambiando únicamente:

```text
assertionSchema = REAL_SHADOW_DATASET
vars.auditDataset = REAL_SHADOW_DATASET
```

Mantener:

```text
defaultSchema = acciones_dataset
vars.operationalDataset = acciones_dataset
vars.environment = shadow
```

Comparar ambas compilation results y demostrar:

- mismo snapshot Dataform;
- mismos `canonicalTarget` y `filePath`;
- mismos doce outputs;
- la única diferencia de destino es
  `VALIDATION_DATASET -> REAL_SHADOW_DATASET`;
- cero compilation errors.

Solo entonces continuar con el orden de materialización del runbook principal.

## 10. Evidencia y no mutación

Conservar:

```text
wp03_schema_compilation_actions.json
wp03_schema_graph_plan.json
wp03_schema_graph_result.json
schema compilation result metadata
validation dataset metadata
real shadow compilation result metadata
comparison of both compilation results
```

Registrar antes y después:

- cero escrituras en `acciones_dataset`;
- cero escrituras en `REAL_SHADOW_DATASET` durante el schema gate;
- ninguna workflow invocation durante el schema gate;
- Dataform production sin cambios;
- Cloud Run sin cambios;
- schedulers sin cambios;
- IAM y Secret Manager sin cambios;
- ningún broker call.

No borrar el dataset schema-check hasta que ChatGPT haya revisado la evidencia.
No reutilizarlo en otro SHA.

## Stop condition

Ante cualquier fallo, devolver todos los errores agregados:

```text
WP-03 compiled SQL schema graph BLOCKED: <todos los errores>;
no production resources modified.
```

Solo con `ALL_COMPILED_ACTIONS_SCHEMA_GRAPH_PASS` puede reanudarse la
materialización shadow real.

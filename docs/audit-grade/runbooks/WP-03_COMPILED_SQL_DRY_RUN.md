# WP-03 — Dry-run semántico agregado de SQL compilado

## Propósito

Validar **todas** las acciones compiladas de WP-03 contra el analizador de
GoogleSQL/BigQuery antes de iniciar una `workflowInvocation` o materializar una
tabla. Este gate existe para detectar en un solo paso:

- nombres de columna ambiguos;
- columnas o tablas inexistentes;
- tipos incompatibles;
- referencias resueltas al dataset incorrecto;
- errores en `UNION ALL`;
- expresiones no reconocidas;
- errores de sintaxis que Dataform compile por sí solo no detecta contra
  BigQuery.

El procedimiento es read-only. Cada consulta se envía con:

```text
dryRun=true
useLegacySql=false
```

No crea jobs de ejecución, no materializa tablas y no autoriza operaciones
productivas.

## Prerrequisitos

- checkout limpio del SHA aprobado;
- compilation result nueva del mismo SHA;
- `defaultDatabase = stocks-437902`;
- `defaultSchema = acciones_dataset`;
- `vars.auditDataset = <SHADOW_DATASET>`;
- `vars.operationalDataset = acciones_dataset`;
- `vars.environment = shadow`;
- dataset shadow con labels `environment=shadow` y `work_package=wp03`;
- cero compilation errors;
- ninguna acción compilada escribe fuera del dataset shadow.

## Acciones obligatorias

Deben aparecer exactamente una vez en el inventario compilado:

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

También deben incluirse las assertions automáticas asociadas a esos modelos.

## 1. Exportar las acciones compiladas

Consulta de forma paginada:

```text
GET projects/<PROJECT_ID>/locations/<LOCATION>/repositories/<REPOSITORY>/
    compilationResults/<COMPILATION_RESULT>:query
```

Conserva una copia sanitizada en:

```text
$WP03_EVIDENCE_TMP/wp03_compilation_actions.json
```

Para cada `CompilationResultAction`:

- `relation.selectQuery` es el SQL de una tabla, vista o materialized view;
- `assertion.selectQuery` es el SQL que debe devolver cero filas;
- `operations.queries[]` contiene cada sentencia de una operación;
- una declaration no se ejecuta ni se dry-runea;
- una acción `disabled=true` no puede contarse como validada.

Registra como mínimo:

```text
target.database
target.schema
target.name
canonicalTarget
filePath
compiled_object_type
disabled
dependencyTargets
sql_sha256
```

No persistas credenciales ni tokens.

## 2. Verificar scope antes del dry-run

Antes de enviar SQL a BigQuery, exige:

```text
relation target dataset = <SHADOW_DATASET>
assertion target dataset = <SHADOW_DATASET>
legacy input references = acciones_dataset
```

Rechaza cualquier SQL que contenga DDL/DML dirigido a:

```text
stocks-437902.acciones_dataset
```

Las lecturas desde `acciones_dataset` son permitidas únicamente para las seis
fuentes operativas autorizadas:

```text
macro_earnings_calendar
trading_price_features
asset_profile
valuation_model_profile
trading_historical_context
portfolio_valuation_daily
```

## 3. Ejecutar dry-run de cada SELECT compilado

Guarda cada `selectQuery` en un archivo temporal identificado por target y
checksum. Ejecuta:

```bash
bq \
  --project_id="$PROJECT_ID" \
  --location="$LOCATION" \
  --format=prettyjson \
  query \
  --use_legacy_sql=false \
  --dry_run \
  < "$COMPILED_SQL_FILE"
```

Para `operations.queries[]`, ejecuta cada sentencia por separado únicamente si
es compatible con dry-run y está limitada al dataset shadow. Si una operación
contiene DDL necesario para crear una tabla raw, valida además sus referencias
y destination mediante la compilation action; no ejecutes la operación en este
gate.

No uses:

```text
--replace
--append_table
--destination_table
workflowInvocation
CREATE
MERGE
INSERT
UPDATE
DELETE
```

como sustituto del dry-run.

## 4. Agregar todos los resultados

No detenerse en el primer error. Recolectar para cada acción:

```text
target
compiled_object_type
sql_sha256
dry_run_status
total_bytes_processed
error_reason
error_message
error_location
```

Guardar:

```text
$WP03_EVIDENCE_TMP/wp03_compiled_sql_dry_runs.json
```

El documento debe contener:

```json
{
  "git_sha": "<FINAL_SHA>",
  "compilation_result": "<RESOURCE_NAME>",
  "project_id": "stocks-437902",
  "location": "us-east1",
  "operational_dataset": "acciones_dataset",
  "shadow_dataset": "<SHADOW_DATASET>",
  "action_count": 12,
  "assertion_count": "<COUNT>",
  "failed_action_count": 0,
  "production_change_allowed": false,
  "status": "ALL_COMPILED_ACTIONS_DRY_RUN_PASS"
}
```

`action_count` cuenta los doce outputs principales; las assertions se registran
por separado.

## 5. Gates obligatorios

No crear ninguna `workflowInvocation` hasta demostrar:

```text
ALL_COMPILED_ACTIONS_DRY_RUN_PASS
failed_action_count = 0
```

Y ausencia total de mensajes equivalentes a:

```text
ambiguous
unrecognized name
not found
no matching signature
incompatible types
column count mismatch
syntax error
```

Un error en cualquier tabla o assertion bloquea todo el grafo. No se corrige
target por target dentro del entorno live: se documentan todos los errores, se
detiene la validación y se devuelve el control al PR de código.

## 6. Evidencia y no mutación

La evidencia final debe incluir:

- SHA exacto del monorepo;
- SHA del snapshot Dataform;
- compilation result;
- listado completo de actions;
- checksum de cada SQL;
- resultado de cada dry-run;
- prueba de que no existió workflow invocation durante el gate;
- prueba de que no hubo DDL/DML;
- prueba de cero escrituras en `acciones_dataset`;
- `production_change_allowed=false`.

Después del gate, repetir el inventario read-only de datasets y jobs para
confirmar que no hubo mutación.

## Stop condition

Ante cualquier fallo responde:

```text
WP-03 compiled SQL dry-run BLOCKED: <todos los errores agregados>;
no production resources modified.
```

Solo con todos los dry-runs en PASS puede continuar la materialización ordenada
del runbook principal.

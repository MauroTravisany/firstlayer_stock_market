# WP-03 — Entry point estable del schema check compilado

## Contrato operativo

El entry point público y estable para la validación semántica del grafo SQL de
WP-03 es:

```text
tools/wp03_compiled_sql_schema_check.py
```

El módulo:

```text
tools/wp03_compiled_sql_semantic_preflight.py
```

es la **internal implementation**. No debe usarse como nombre contractual en
mensajes de handoff, automatizaciones externas o instrucciones para Codex.

El entry point estable reexporta exactamente el planificador, las validaciones
de alcance y el ejecutor schema-only de la implementación revisada. Ejecutarlo
como script es equivalente a ejecutar el módulo interno:

```bash
python tools/wp03_compiled_sql_schema_check.py --help
```

## Resultado exitoso

En modo de ejecución, la única conclusión aceptable es:

```text
status = ALL_COMPILED_ACTIONS_SCHEMA_GRAPH_PASS
failed_action_count = 0
failed_assertion_count = 0
validation_dataset_only = true
production_change_allowed = false
```

El dataset de validación debe:

- contener `shadow` y `schema` en su nombre;
- estar separado de `acciones_dataset`;
- estar separado del dataset shadow real de evidencia;
- tener labels `environment=shadow`, `work_package=wp03` y
  `purpose=compiled_sql_validation`;
- estar vacío antes de iniciar el gate.

La herramienta crea únicamente una tabla raw vacía desde el contrato y vistas
`WHERE FALSE` para validar schemas y dependencias. No materializa datos de
investigación ni autoriza escritura en producción.

## Comando de plan

```bash
python tools/wp03_compiled_sql_schema_check.py \
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

## Comando de ejecución

```bash
python tools/wp03_compiled_sql_schema_check.py \
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

## Stop conditions

No continuar a una `workflowInvocation` del shadow real si:

- el HEAD no tiene CI completo en `success`;
- el checkout no coincide exactamente con el SHA aprobado;
- falta el entry point estable;
- el plan checksum cambia;
- aparece cualquier acción `FAIL` o `BLOCKED_BY_FAILED_DEPENDENCY`;
- una assertion no pasa;
- un target escribe fuera del dataset de validación;
- existe cualquier intento de escribir en `acciones_dataset` o en el shadow
  real durante este gate.

Los runs `action_required` sin jobs no constituyen evidencia CI válida.

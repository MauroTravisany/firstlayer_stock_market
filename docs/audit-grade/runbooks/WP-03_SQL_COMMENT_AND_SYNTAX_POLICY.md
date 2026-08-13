# WP-03 — Política de comentarios y validación sintáctica SQL

## Problema resuelto

El plan del schema graph rechazó `wp03_legacy_invalidation` aun cuando su SQL
era GoogleSQL válido. La consulta comenzaba con documentación `-- ...` antes
de `WITH`, mientras el preflight comprobaba el primer token sin ignorar
comentarios.

No se eliminan comentarios útiles para el auditor. El validador ahora distingue
entre documentación y SQL ejecutable.

## Comentarios admitidos

La política lexical reconoce, fuera de strings e identificadores:

```sql
-- comentario de línea
# comentario de línea GoogleSQL
/* comentario de bloque */
```

También reconoce strings simples, dobles, triples y backticks. Por tanto,
secuencias como `--`, `#` o `/* */` dentro de un literal no cambian el análisis.
Un bloque o literal sin cierre falla de forma cerrada.

## Dos representaciones, un solo SQL original

- El SQL original se conserva íntegro para `sql_sha256`, evidencia y BigQuery.
- Una copia enmascarada se usa solamente para verificar que una relación o
  assertion comienza con `SELECT`/`WITH` y no contiene una mutación.
- Otra copia enmascara además strings para que palabras como `DROP` dentro de un
  reason code no parezcan instrucciones.
- Los identificadores entre backticks se conservan para detectar destinos de
  escritura.

Versión de política:

```text
wp03-google-sql-comment-aware-v1
```

## Cobertura de todo el grafo

Las pruebas recorren los doce SQLx WP-03 y verifican que, después del bloque
`config` y de ignorar comentarios válidos:

- `financial_statements_pit_raw` comienza con `CREATE TABLE`;
- las once relaciones/assertions restantes comienzan con `SELECT` o `WITH`;
- no existe comentario de bloque sin cierre;
- comentarios con palabras `CREATE`, `DROP`, `MERGE`, `UPDATE` o `DELETE` no
  producen falsos positivos;
- una mutación ejecutable después de comentarios sigue siendo rechazada;
- el plan acepta comentarios en todos los outputs requeridos.

## Autoridad final de sintaxis

El lexer local evita falsos bloqueos y aplica controles de seguridad, pero no
pretende reemplazar el parser de BigQuery. Antes de materializar el shadow real,
Codex debe ejecutar mediante:

```text
tools/wp03_compiled_sql_schema_check.py
```

el schema graph completo y exigir:

```text
status = ALL_COMPILED_ACTIONS_SCHEMA_GRAPH_PASS
failed_action_count = 0
failed_assertion_count = 0
validation_dataset_only = true
production_change_allowed = false
```

El schema graph agrega todos los errores de ramas independientes y marca los
descendientes bloqueados. No se permite corregir una tabla live y continuar a
ciegas con la siguiente.

## Seguridad

Este cambio no autoriza deploy, Dataform production, Terraform apply, cambios
de scheduler/IAM/Secret Manager, Strategy Brain, broker ni escrituras en
`acciones_dataset`.

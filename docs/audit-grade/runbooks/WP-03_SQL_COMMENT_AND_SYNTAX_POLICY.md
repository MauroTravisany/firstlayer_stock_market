# WP-03 — Política de comentarios y validación sintáctica SQL

## Objetivo

WP-03 no puede depender de que un operador descubra errores GoogleSQL uno por
uno durante la materialización BigQuery. La política combina tres controles:

1. compilación Dataform;
2. preflight lexical/estructural local sobre las doce acciones;
3. schema graph real contra BigQuery en un dataset desechable.

Ninguno sustituye a los demás.

## Comentarios admitidos

La política lexical reconoce, fuera de strings e identificadores:

```sql
-- comentario de línea
# comentario de línea GoogleSQL
/* comentario de bloque */
```

También reconoce strings simples, dobles, triples y backticks. Secuencias como
`--`, `#` o `/* */` dentro de un literal no cambian el análisis. Un comentario,
literal o identificador sin cierre falla de forma cerrada.

## SQL original y copias enmascaradas

- El SQL original se conserva íntegro para `sql_sha256`, evidencia y BigQuery.
- Una copia sin comentarios verifica el primer statement.
- Una copia sin strings evita que palabras como `DROP` dentro de un reason code
  parezcan instrucciones.
- Los identificadores entre backticks se conservan cuando se inspeccionan
  destinos de lectura o escritura.

Política de comentarios:

```text
wp03-google-sql-comment-aware-v1
```

## Política estática de sintaxis

Versión:

```text
wp03-google-sql-static-syntax-v1
```

La política aplica a las doce acciones WP-03 y a las assertions generadas. Antes
de ejecutar BigQuery verifica:

- paréntesis y corchetes balanceados;
- conteo balanceado de `CASE` y `END`;
- CTE, aliases explícitos y aliases de tabla que no usen keywords reservadas sin
  backticks;
- statement inicial `SELECT`/`WITH` para relaciones y assertions;
- `CREATE TABLE` único y dirigido al raw shadow para la operación raw;
- ausencia de SQL mutante o escrituras operativas.

GoogleSQL prohíbe utilizar keywords reservadas como identificadores no citados.
El defecto que motivó esta versión era:

```sql
FROM latest_quarter current
```

`CURRENT` es reservado. El modelo usa ahora aliases descriptivos no reservados:

```sql
FROM latest_quarter cur_q
LEFT JOIN financial_quarters_pit prior_q
```

También se bloquean casos como:

```sql
SELECT COUNT(*) AS rows
WITH current AS (...)
```

Los tipos y construcciones válidas no son aliases y permanecen permitidos:

```sql
CAST([] AS ARRAY<STRING>)
SELECT AS STRUCT
CURRENT_TIMESTAMP()
```

## Cobertura de todo el grafo

`tests/unit/wp03/test_wp03_sql_static_syntax.py` recorre:

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

La prueba agrega todos los problemas encontrados y los presenta juntos. También
incluye regresiones para aliases `current` y `rows`, delimitadores, `CASE/END`,
comentarios y funciones `CURRENT_*` válidas.

## Autoridad final: BigQuery schema graph

El linter local detecta errores estructurales y el uso de keywords reservadas,
pero no pretende reemplazar el parser, el resolved schema ni el type checker de
BigQuery. Antes de materializar el shadow real, Codex debe ejecutar:

```text
tools/wp03_compiled_sql_schema_check.py
```

El gate obligatorio es:

```text
status = ALL_COMPILED_ACTIONS_SCHEMA_GRAPH_PASS
failed_action_count = 0
failed_assertion_count = 0
required_action_count = 12
required_assertion_count = 1
validation_dataset_only = true
production_change_allowed = false
```

El schema graph agrega errores de ramas independientes y marca descendientes
bloqueados. Si un upstream falla, no se interpreta el bloqueo de sus
descendientes como validación de esos descendientes; la revisión estática y
manual sigue siendo obligatoria antes del reintento.

## Seguridad

Esta política no autoriza deploy, Dataform production, Terraform apply, cambios
de Scheduler/IAM/Secret Manager, Strategy Brain, broker ni escrituras en
`acciones_dataset`.

# WP-03 — Tipos nativos de acciones del schema graph

## Contrato

El inventario WP-03 contiene **12 acciones requeridas**, no doce relaciones:

| Acción | Tipo Dataform requerido | Tratamiento schema-only |
|---|---|---|
| `financial_statements_pit_raw` | `operations` | tabla vacía desde contrato |
| diez modelos PIT intermedios/finales | `relation` | vista lógica con guard `WHERE FALSE` |
| `audit_no_lookahead` | `assertion` | dry-run y vista lógica con guard `WHERE FALSE` |

La política se identifica como:

```text
wp03-native-action-types-v1
```

## Razón

`audit_no_lookahead.sqlx` declara correctamente:

```text
type: "assertion"
```

No debe convertirse en `table` o `view` para satisfacer una herramienta. El
preflight adapta la acción solamente en memoria para reutilizar el planificador
topológico revisado, y restaura su tipo `assertion` antes de:

- generar `required_actions`;
- calcular el checksum del plan;
- ejecutar el schema graph;
- registrar evidencia.

El SQL compilado no se modifica.

## Conteos de evidencia

El plan debe declarar:

```text
required_action_count = 12
required_action_type_counts.operations = 1
required_action_type_counts.relation = 10
required_action_type_counts.assertion = 1
required_assertion_count = 1
generated_assertion_count = <assertions automáticas Dataform>
total_assertion_count = required_assertion_count + generated_assertion_count
```

El campo histórico `assertion_count` se conserva y representa únicamente las
assertions generadas asociadas a modelos. La assertion requerida
`audit_no_lookahead` se cuenta por separado para no alterar evidencia previa de
forma ambigua.

## No duplicación

`audit_no_lookahead` debe:

- aparecer exactamente una vez en `required_actions`;
- aparecer en el orden topológico después de sus dependencias;
- ejecutarse exactamente una vez durante el schema graph;
- no reaparecer en la colección de assertions generadas;
- producir fallo del schema graph si su SQL no compila.

## Gate de operador

El entrypoint estable:

```text
tools/wp03_compiled_sql_schema_check.py
```

usa el planificador estricto y rechaza:

- `audit_no_lookahead` compilado como `relation`;
- `audit_no_lookahead` compilado como `operations`;
- cualquier required action ausente, duplicada, deshabilitada o fuera del
  dataset de validación;
- dependencias operativas no autorizadas;
- SQL mutante o sintácticamente inválido.

La compatibilidad con la fixture unitaria histórica que representaba el audit
como relation queda aislada en la API de pruebas; el CLI operativo siempre usa
los tipos nativos estrictos.

## Resultado requerido

No se puede avanzar al shadow real salvo que:

```text
status = ALL_COMPILED_ACTIONS_SCHEMA_GRAPH_PASS
failed_action_count = 0
failed_assertion_count = 0
required_action_count = 12
required_assertion_count = 1
validation_dataset_only = true
production_change_allowed = false
```

Esta validación sigue siendo schema-only. La condición de contenido
`audit_no_lookahead = 0` se verifica posteriormente durante la materialización
shadow real.

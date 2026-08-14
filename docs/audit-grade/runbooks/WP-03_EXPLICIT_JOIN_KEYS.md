# WP-03 — Política de claves de join explícitas

## Problema

BigQuery resuelve `JOIN ... USING (...)` fusionando columnas del mismo nombre.
Cuando ese resultado compuesto participa en otro join, una clave como
`analysis_date` puede quedar ambigua en el lado izquierdo aunque cada tabla de
origen la declare una sola vez.

El incidente se manifestó en `wp03_legacy_vs_pit_shadow` al encadenar dos joins
con `USING (analysis_date, signal_hour, ticker)`.

## Contrato

WP-03 prohíbe `JOIN ... USING` en sus doce acciones requeridas. Cada join debe
usar un predicado `ON` explícito y completamente calificado:

```sql
LEFT JOIN right_side r
  ON r.analysis_date = p.analysis_date
 AND r.signal_hour = p.signal_hour
 AND r.ticker = p.ticker
```

Versión de política:

```text
wp03-explicit-join-keys-v1
```

## Alcance de la corrección

Se reemplazaron los joins implícitos en:

- `wp03_legacy_vs_pit_shadow`;
- `trading_earnings_context_pit`;
- `portfolio_valuation_pit_shadow`.

Las fórmulas, cardinalidad pretendida, semántica point-in-time, reglas de
moneda y selección de revisiones permanecen sin cambios.

## Gates

`tools/wp03_join_policy.py` inspecciona SQL ejecutable después de enmascarar
comentarios, strings e identificadores. El schema graph llama esta política
antes de producir el plan y registra:

```text
join_key_policy_version = wp03-explicit-join-keys-v1
```

La suite de regresión:

- reproduce el encadenamiento ambiguo de dos `USING`;
- comprueba que comentarios y literales no produzcan falsos positivos;
- recorre los doce SQLX WP-03 en una única prueba agregada;
- exige ownership explícito de `analysis_date`, `signal_hour` y `ticker` en los
  tres modelos multi-join afectados;
- demuestra que el entrypoint del schema graph rechaza SQL compilado con
  `JOIN ... USING` antes de BigQuery.

## Autoridad final

Esta política elimina una clase completa de ambigüedad, pero no sustituye el
parser ni el type checker reales. Codex debe regenerar y ejecutar el schema
graph completo desde el SHA final y exigir cero acciones o assertions fallidas.

## Seguridad

El cambio no autoriza deploy, Dataform production, Terraform apply, cambios de
Scheduler/IAM/Secret Manager, Strategy Brain, broker ni escrituras en
`acciones_dataset`.

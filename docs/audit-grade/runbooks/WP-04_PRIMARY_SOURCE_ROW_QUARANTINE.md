# WP-04 — Cuarentena de filas defectuosas de la fuente primaria

## Autoridad

Este runbook reemplaza cualquier instrucción que obligue a abortar todo el plan
WP-04 por una única fila Yahoo malformada. No reduce la obligatoriedad de Yahoo,
no modifica precios y no autoriza completar datos ausentes.

La política canónica es:

```text
wp04-primary-row-quarantine-v1
```

El planificador autorizado continúa siendo:

```text
tools/wp04_shadow_backfill_windowed.py
```

Ese entrypoint utiliza `tools/wp04_quarantine_planner.py`, que envuelve el
planificador resiliente ya revisado y liga la evidencia de cuarentena al
`plan_checksum`.

## Causa raíz cubierta

Yahoo entregó para `CLP=X`, intervalo `1d`, una fila del `2024-01-01` con OHLC
inconsistente. Esa fecha no pertenece al calendario canónico FX porque Año Nuevo
es una sesión cerrada. La fila no debe corregirse ni insertarse; debe quedar
registrada como:

```text
reason_code = OUTSIDE_CANONICAL_SESSION
disposition = QUARANTINED
```

El calendario `FX_24_5` excluye ahora Año Nuevo y Navidad, incluidas sus fechas
observadas. No se infieren otros feriados específicos de moneda o venue sin una
fuente de calendario versionada separada.

## Principio de seguridad

La política es:

```text
QUARANTINE_WITHOUT_REPAIR
```

Está prohibido:

- modificar `open`, `high`, `low` o `close` para hacerlos consistentes;
- reemplazar la fila con datos de otra fecha;
- copiar datos de otra fuente y etiquetarlos como Yahoo;
- interpolar OHLC o volumen;
- ocultar el rechazo mediante retries silenciosos;
- insertar la fila rechazada en `market_price_raw`;
- eliminar la evidencia de la anomalía.

## Clasificación de filas

Antes de normalizar cada fila Yahoo se valida:

- pertenencia al calendario canónico;
- precios requeridos presentes, numéricos, finitos y positivos;
- `high >= max(open, low, close)`;
- `low <= min(open, high, close)`;
- adjusted close positivo cuando existe;
- volumen no negativo cuando existe;
- timestamp y ventana temporal válidos.

Reason codes incluyen:

```text
OUTSIDE_CANONICAL_SESSION
MISSING_REQUIRED_PRICE
NON_NUMERIC_VALUE
NON_FINITE_VALUE
NON_POSITIVE_PRICE
OHLC_INCONSISTENT
INVALID_ADJUSTED_CLOSE
NEGATIVE_VOLUME
```

Los valores OHLC rechazados no se guardan en el artefacto. Solo se conserva un
`payload_hash` SHA-256, el timestamp, la identidad de la serie y el reason code.

## Gates de la fuente primaria

Yahoo continúa siendo obligatorio a nivel de serie. Cada serie debe conservar al
menos una fila válida después de la cuarentena.

Las filas fuera de sesión se registran, pero no cuentan como corrupción de una
sesión válida. Las filas inválidas dentro de sesión deben cumplir ambos límites:

```text
MIN_VALID_ROW_RATIO = 0.995
MAX_INVALID_ROWS_PER_SERIES = 5
```

Si una serie queda vacía, supera cinco filas inválidas o cae por debajo de
`0.995`, el plan falla antes de cualquier escritura BigQuery.

Este gate permite aislar una anomalía materialmente pequeña sin convertir un
feed degradado en PASS.

## Artefactos ligados al checksum

El plan debe incluir dentro de `files`:

```text
primary_source_status
primary_source_rejections
```

`primary_source_status.jsonl` contiene una fila por serie Yahoo requerida con:

```text
status_id
policy_version
provider
ticker
provider_symbol
source_interval
required
status
raw_row_count
eligible_row_count
accepted_row_count
rejected_row_count
off_session_row_count
invalid_row_count
valid_row_ratio
minimum_valid_row_ratio
maximum_invalid_rows
reason_counts
observed_at
production_change_allowed
```

`primary_source_rejections.jsonl` contiene únicamente metadata sanitizada:

```text
rejection_id
policy_version
provider
ticker
provider_symbol
asset_type
exchange
source_interval
source_timezone
event_time
reason_code
payload_hash
disposition
observed_at
production_change_allowed
```

Ambos archivos incluyen SHA-256, row count e identity-set hash dentro del plan.
Alterar un archivo invalida `plan_checksum`.

## Cobertura mínima

Después de la cuarentena debe seguir existiendo cobertura primaria:

- Yahoo `1d` y `15m` para AAPL, MSFT, NVDA, META y AMZN;
- Yahoo `1h` para BTC-USD y ETH-USD;
- Yahoo `1d` para CLP=X;
- calendarios XNYS, CRYPTO_24_7 y FX_24_5.

Una fila de Año Nuevo rechazada no reemplaza esta cobertura ni la amplía.

## Fuente secundaria

La política de Stooq continúa siendo:

```text
wp04-secondary-source-configurable-v1
```

En modo opcional, una fila Stooq con OHLC inválido clasifica la fuente como
`UNAVAILABLE` con reason code `INVALID_OHLC`; no se inserta y no se presenta como
reconciliación válida. En modo estricto continúa fallando antes de escribir.

## Evidencia y ejecución

Antes de ejecutar el backfill, revisar:

```text
provider_versions.PRIMARY_SOURCE_POLICY = wp04-primary-row-quarantine-v1
primary_source_policy.required = true
primary_source_policy.disposition = QUARANTINE_WITHOUT_REPAIR
primary_source_status.row_count > 0
primary_source_rejections.sha256 = SHA-256 válido
production_change_allowed = false
```

La ejecución usa únicamente las tres tablas raw autorizadas. Los archivos de
status y rechazo son evidencia checksum-bound; no son tablas de mercado y no se
insertan en BigQuery.

El replay idempotente debe usar exactamente el mismo plan y los mismos archivos.
No puede volver a consultar Yahoo ni Stooq.

## Prohibiciones

No hacer merge, no cerrar Issue #39, no avanzar a WP-05, no escribir en
`acciones_dataset`, no desplegar Cloud Run, no mover Dataform production, no
ejecutar Terraform apply, no modificar Scheduler/IAM/Secret Manager y no llamar
al broker.

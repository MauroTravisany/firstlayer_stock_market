# WP-04 — Reintento con ventana móvil Yahoo

## Autoridad

Este documento reemplaza exclusivamente las secciones de planificación y
backfill del runbook
`WP-04_CANONICAL_PRICE_SHADOW_VALIDATION.md` para todo intento posterior al
bloqueo de Yahoo 15m. El resto de los gates, prohibiciones y evidencia del
runbook principal continúan vigentes.

El planificador autorizado es:

```text
tools/wp04_shadow_backfill_windowed_official_fx.py
```

Los entrypoints `tools/wp04_shadow_backfill.py` y
`tools/wp04_shadow_backfill_windowed.py` están retirados para asset-set v2 y
fallan cerrados. La ejecución autorizada es
`tools/wp04_shadow_backfill_official_fx.py`.

## Causa raíz

Yahoo aplica la retención de barras intradía contra el reloj actual del
proveedor, no contra el `END_DATE` histórico solicitado. Una fecha puede ser
válida en relación con el final del backfill y quedar fuera de la ventana móvil
cuando se ejecuta el plan días después.

La política canónica y única es:

```text
wp04-yahoo-moving-window-v1
```

El identificador anterior queda retirado y no es válido para un plan nuevo:

```text
wp04-yahoo-provider-window-v1
```

Todo documento o plan que utilice el identificador retirado debe regenerarse
desde el HEAD aprobado. No se permite editar manualmente el campo
`policy_version` porque forma parte del `window_checksum` y del
`plan_checksum`.

- 15m: retención declarada de 60 días, lookback máximo conservador de 58 días;
- 1h: retención declarada de 730 días, lookback máximo conservador de 728 días;
- `END_DATE` se resuelve como fecha UTC del proveedor menos dos días;
- la resolución, el anchor UTC y las fechas efectivas forman parte del
  `plan_checksum`.

## Regeneración obligatoria

Todo checkout, candidate branch, compilation result, plan, JSONL, checksum o
evidencia ligado a un SHA anterior es obsoleto. No reutilizar el plan que falló
por `2026-06-16` ni un plan que declare la política retirada.

Después de aprobar nuevamente el schema graph y de materializar vacías las
cuatro tablas raw del shadow real, definir:

```bash
FINAL_SHA=<SHA_APROBADO>
PROJECT_ID=stocks-437902
LOCATION=us-east1
REAL_SHADOW_DATASET=<DATASET_SHADOW_NUEVO>
ASSET_SET=config/wp04_shadow_assets.v1.json
WP04_EVIDENCE_TMP=/tmp/wp04-shadow-evidence
```

Crear un plan actual y acotado:

```bash
rm -rf "$WP04_EVIDENCE_TMP/backfill"
mkdir -p "$WP04_EVIDENCE_TMP/backfill"

python tools/wp04_shadow_backfill_windowed_official_fx.py \
  --expected-git-sha "$FINAL_SHA" \
  --asset-set "$ASSET_SET" \
  --daily-start-date 2024-01-01 \
  --end-lag-days 2 \
  --intraday-lookback-days 45 \
  --hourly-lookback-days 365 \
  --max-rows 100000 \
  --work-dir "$WP04_EVIDENCE_TMP/backfill" \
  --window-output \
    "$WP04_EVIDENCE_TMP/wp04_provider_window.json" \
  --bcch-api-token-env BCCH_API_TOKEN \
  --output \
    "$WP04_EVIDENCE_TMP/wp04_shadow_backfill_plan.json"
```

## Revisión obligatoria antes de escribir

Los dos archivos deben declarar el mismo:

```text
provider_window_policy.policy_version = wp04-yahoo-moving-window-v1
provider_window_checksum = provider_window_policy.window_checksum
```

Revisar y registrar:

```text
anchor_at_utc
provider_anchor_date
start_date
end_date
intraday_start_date
hourly_start_date
end_lag_days
intraday.retention_days
intraday.safety_buffer_days
intraday.safe_lookback_days
intraday.lookback_days
intraday.earliest_safe_start_date
hourly.retention_days
hourly.safety_buffer_days
hourly.safe_lookback_days
hourly.lookback_days
hourly.earliest_safe_start_date
window_checksum
plan_checksum
```

Exigir:

```text
intraday.safe_lookback_days = 58
intraday.lookback_days = 45
hourly.safe_lookback_days = 728
hourly.lookback_days = 365
intraday.within_provider_window = true
hourly.within_provider_window = true
production_change_allowed = false
```

No editar manualmente ninguna fecha, política, checksum o JSONL. Cualquier
alteración debe invalidar la ejecución.

Revisar además:

- siete activos de mercado no FX del asset set versionado;
- Yahoo daily/15m/1h y Stooq daily según tipo de activo;
- BCCh `F073.TCO.PRE.Z.D` como única tasa USD/CLP elegible;
- checksums e identity-set hashes de los cuatro JSONL raw;
- `total_row_count <= 100000`;
- ninguna ruta o destino operacional.

## Ejecución append-only

Extraer el nuevo `plan_checksum` y ejecutar con el entrypoint de escritura
shadow:

```bash
python tools/wp04_shadow_backfill_official_fx.py \
  --expected-git-sha "$FINAL_SHA" \
  --execute \
  --plan-file \
    "$WP04_EVIDENCE_TMP/wp04_shadow_backfill_plan.json" \
  --expected-plan-checksum "$WP04_PLAN_CHECKSUM" \
  --acknowledge-shadow-write WP04_SHADOW_WRITE \
  --project-id "$PROJECT_ID" \
  --dataset-id "$REAL_SHADOW_DATASET" \
  --location "$LOCATION" \
  --environment shadow \
  --output \
    "$WP04_EVIDENCE_TMP/wp04_shadow_backfill_execution.json"
```

La ejecución debe verificar la política de proveedor y el checksum antes de
crear staging o escribir. No refetchea datos.

Repetir exactamente el mismo comando y guardar el resultado como:

```text
wp04_shadow_backfill_idempotence.json
```

El replay debe insertar cero filas en:

```text
market_price_raw
corporate_actions_pit
market_session_calendar
fx_rate_raw
```

## Continuación

Después de demostrar idempotencia, continuar con la materialización ordenada,
la evidencia read-only, el inventario after y la prueba de cero mutación del
runbook principal.

No hacer merge, no cerrar Issue #39, no avanzar a WP-05, no escribir en
`acciones_dataset`, no desplegar Cloud Run, no mover Dataform production, no
ejecutar Terraform apply y no llamar al broker.

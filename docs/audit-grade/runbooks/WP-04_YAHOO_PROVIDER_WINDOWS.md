# WP-04 — Ventanas móviles de Yahoo

## Precedencia

Este documento reemplaza las fechas fijas de la sección 11 de
`WP-04_CANONICAL_PRICE_SHADOW_VALIDATION.md`.

Yahoo calcula la retención intradía contra la fecha real de la consulta. Por
eso una fecha 15m válida al redactar el runbook puede quedar fuera de ventana
días después.

## Política

```text
policy_version = wp04-yahoo-moving-window-v1
end lag UTC = 2 días
15m retention = 60 días
15m safety buffer = 2 días
15m requested lookback = 45 días
1h retention = 730 días
1h safety buffer = 2 días
1h requested lookback = 365 días
```

Las fechas no se escriben manualmente. El planner windowed las resuelve en el
momento de ejecución y luego llama al planner append-only ya revisado.

## Comando obligatorio

```bash
mkdir -p /tmp/wp04-shadow-evidence/backfill

python tools/wp04_shadow_backfill_windowed.py \
  --expected-git-sha "$FINAL_SHA" \
  --asset-set config/wp04_shadow_assets.v1.json \
  --daily-start-date 2024-01-01 \
  --end-lag-days 2 \
  --intraday-lookback-days 45 \
  --hourly-lookback-days 365 \
  --max-rows 100000 \
  --work-dir /tmp/wp04-shadow-evidence/backfill \
  --window-output \
    /tmp/wp04-shadow-evidence/wp04_provider_window.json \
  --output \
    /tmp/wp04-shadow-evidence/wp04_shadow_backfill_plan.json
```

No ejecutar el modo de planificación de `wp04_shadow_backfill.py` con fechas
copiadas de un intento anterior.

## Gates

`wp04_provider_window.json` debe demostrar:

```text
operation = WP04_PROVIDER_WINDOW_RESOLUTION
policy_version = wp04-yahoo-moving-window-v1
intraday.within_provider_window = true
hourly.within_provider_window = true
production_change_allowed = false
window_checksum = SHA-256 válido
```

El plan debe contener las mismas fechas y:

```text
provider_window_checksum =
  wp04_provider_window.json.window_checksum
```

El `plan_checksum` existente continúa ligando las fechas efectivas, assets,
archivos JSONL y scope de escritura. La ejecución y el replay siguen usando
`tools/wp04_shadow_backfill.py --execute` con ese checksum exacto.

## Evidencia

Comprometer sanitizado:

```text
docs/audit-grade/evidence/wp04_provider_window.json
```

No proporcionar una fecha ancla histórica, no ampliar las ventanas y no
fabricar cobertura intradía.
# WP-04 — Outage de la fuente secundaria Stooq

## Autoridad

Este runbook reemplaza únicamente cualquier instrucción operativa que trate a
Stooq como requisito incondicional para la validación shadow de WP-04.

Issue #39 exige una **segunda fuente/reconciliación configurable**. La
compilación shadow aprobada usa:

```text
vars.requireSecondaryPriceSource = "false"
```

Por tanto, Yahoo continúa siendo la fuente primaria obligatoria y Stooq es una
fuente secundaria opcional durante este closeout shadow. Un mismatch material
observado continúa bloqueando calidad; una fuente secundaria no disponible se
registra como warning y produce `SOURCE_MISSING`/`CANONICAL_SINGLE_SOURCE` sin
fabricar datos.

Política:

```text
wp04-secondary-source-configurable-v1
```

## Seguridad del acceso

El código:

- no ejecuta JavaScript;
- no resuelve CAPTCHA;
- no intenta eludir desafíos del proveedor;
- no persiste HTML recibido en lugar de CSV;
- no imprime ni compromete `STOOQ_API_KEY`;
- clasifica el fallo mediante reason codes sanitizados.

Reason codes esperables incluyen:

```text
JAVASCRIPT_CHALLENGE
HTML_RESPONSE
ACCESS_DENIED
RATE_LIMITED
NETWORK_ERROR
HTTP_ERROR
INVALID_CSV_SCHEMA
INVALID_CSV_ROW
NO_DATA
```

## Planificador autorizado

Usar exclusivamente:

```text
tools/wp04_shadow_backfill_windowed_official_fx.py
```

En modo opcional —el modo aprobado para este shadow— **no** pasar:

```text
--require-secondary-source
```

Puede existir una clave oficial en la variable privada:

```text
STOOQ_API_KEY
```

Su ausencia no es un blocker en modo opcional. Su valor nunca debe aparecer en
el plan, logs sanitizados o evidencia.

Ejemplo:

```bash
python tools/wp04_shadow_backfill_windowed_official_fx.py \
  --expected-git-sha "$FINAL_SHA" \
  --asset-set config/wp04_shadow_assets.v1.json \
  --daily-start-date 2024-01-01 \
  --end-lag-days 2 \
  --intraday-lookback-days 45 \
  --hourly-lookback-days 365 \
  --max-rows 100000 \
  --work-dir "$WP04_EVIDENCE_TMP/backfill" \
  --window-output "$WP04_EVIDENCE_TMP/wp04_provider_window.json" \
  --bcch-api-token-env BCCH_API_TOKEN \
  --output "$WP04_EVIDENCE_TMP/wp04_shadow_backfill_plan.json"
```

## Evidencia checksum-bound

El plan debe incluir dentro de `files`:

```text
secondary_source_status
```

El archivo content-addressed asociado debe contener exactamente una fila para
cada acción/ETF configurado para reconciliación. Cada fila declara:

```text
policy_version
provider
ticker
provider_symbol
status
reason_code
required
authentication_mode
row_count
observed_at
production_change_allowed
```

Exigir:

```text
policy_version = wp04-secondary-source-configurable-v1
provider = STOOQ
required = false
production_change_allowed = false
status IN (AVAILABLE, UNAVAILABLE)
```

Si `status=AVAILABLE`:

```text
row_count > 0
reason_code IS NULL
```

Si `status=UNAVAILABLE`:

```text
row_count = 0
reason_code IS NOT NULL
```

El archivo y su SHA-256 forman parte de `files`, por lo que están ligados al
`plan_checksum`. No editar el archivo ni el plan.

El plan debe declarar además:

```text
provider_versions.SECONDARY_SOURCE_POLICY =
  wp04-secondary-source-configurable-v1

provider_versions.SECONDARY_SOURCE_MODE = OPTIONAL
```

## Cobertura obligatoria

Aun cuando Stooq esté no disponible, el plan debe contener:

- Yahoo 1d y 15m para AAPL, MSFT, NVDA, META y AMZN;
- Yahoo 1h para BTC-USD y ETH-USD;
- BCCh `F073.TCO.PRE.Z.D` para USD/CLP;
- calendarios XNYS, CRYPTO_24_7 y FX_24_5.

No exigir filas Stooq cuando todas sus filas de estado demuestren de forma
checksum-bound un outage opcional.

## Materialización y reconciliación

`price_source_reconciliation` debe materializar una fila por ticker/sesión de
la fuente primaria. Sin Stooq:

```text
status = SOURCE_MISSING
blocks_quality = false
```

porque `requireSecondaryPriceSource=false`.

`market_price_canonical` debe conservar:

```text
reconciliation_status = SOURCE_MISSING
quality_status = CANONICAL_SINGLE_SOURCE
```

No se permite convertir un mismatch o una fuente stale en single-source
aceptado. Solo la ausencia de la fuente secundaria opcional puede seguir esta
ruta.

## Evidencia final

Ejecutar el capturador con el modo explícito:

```bash
export WP04_REQUIRE_SECONDARY_SOURCE=false

python tools/wp04_shadow_evidence.py \
  --project-id "$PROJECT_ID" \
  --dataset-id "$REAL_SHADOW_DATASET" \
  --location "$LOCATION" \
  --environment shadow \
  --git-sha "$FINAL_SHA" \
  --ci-run-id "$CI_RUN_ID" \
  --output "$WP04_EVIDENCE_TMP/wp04_shadow_evidence.json"
```

Es válido obtener warnings:

```text
SECONDARY_SOURCE_UNAVAILABLE_OPTIONAL
SECONDARY_SOURCE_MISSING
```

pero continúan siendo hard gates:

```text
UNBLOCKED_RECONCILIATION_PROBLEM
MATERIAL_MISMATCH_NOT_BLOCKED
STALE_SOURCE no bloqueada
RAW/CANONICAL duplicados
availability violations
invalid OHLC
mixed daily/intraday
invalid crypto buckets
invalid FX
blocked price consumption
promotion violations
production-change violations
```

El cierre exige todavía:

```text
evaluation.status = PASS
hard_gate_count = 0
audit_canonical_prices.violation_count = 0
```

## Modo estricto futuro

Para una validación que requiera obligatoriamente dos proveedores:

```text
--require-secondary-source
WP04_REQUIRE_SECONDARY_SOURCE=true
```

En ese modo cualquier outage de Stooq bloquea antes de escribir. Para dinero
real deberá configurarse una fuente secundaria con credenciales/licencia y SLA
adecuados; este runbook no autoriza dinero real.

## Prohibiciones

No hacer merge, no cerrar Issue #39, no avanzar a WP-05, no escribir en
`acciones_dataset`, no desplegar Cloud Run, no mover Dataform production, no
ejecutar Terraform apply, no modificar Scheduler/IAM/Secret Manager y no llamar
al broker.

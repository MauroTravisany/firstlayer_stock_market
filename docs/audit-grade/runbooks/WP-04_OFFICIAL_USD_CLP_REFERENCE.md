# WP-04 — Referencia oficial USD/CLP

## Autoridad

Este runbook reemplaza cualquier instrucción que use `CLP=X` de Yahoo como
fuente obligatoria del tipo de cambio histórico USD/CLP. El diagnóstico live
demostró 44 velas diarias con inconsistencias OHLC materiales y estables entre
descargas. Los thresholds no se relajan y esas velas no se reparan.

Fuente obligatoria:

```text
provider = BCCH_BDE
series_id = F073.TCO.PRE.Z.D
policy_version = wp04-bcch-observed-dollar-v1
source_version = bcch-bde-rest-v1
```

## Credencial privada

La API BDE requiere `BCCH_API_TOKEN`. El token no se escribe en el plan, no se
imprime en errores, no se compromete, no aparece en status JSONL y no forma
parte de hashes públicos. Si falta o es rechazado, el plan falla antes de
cualquier escritura.

## Semántica point-in-time

La API entrega fecha, valor y status, pero no un timestamp de publicación
verificable. Por tanto:

```text
availability_policy = CONSERVATIVE_NEXT_LOCAL_DAY
source_timezone = America/Santiago
available_at = siguiente medianoche local después de rate_date
```

## Representación raw

```text
provider = BCCH_BDE
provider_symbol = F073.TCO.PRE.Z.D
ticker = CLP=X
asset_type = FX
exchange = FX_24_5
source_interval = 1d
quality_status = RAW_REFERENCE_RATE_VALIDATED
open = NULL
high = NULL
low = NULL
close = NULL
volume = NULL
adjusted_close = rate
```

No es una vela ejecutable. `market_price_canonical` conserva únicamente barras
tradables `RAW_VALIDATED`; `fx_rates_pit` consume las revisiones BCCh.

## Evidencia

El plan debe contener `files.fx_reference_status`,
`provider_versions.BCCH_BDE=bcch-bde-rest-v1` y
`provider_versions.FX_REFERENCE_POLICY=wp04-bcch-observed-dollar-v1`.

La evidencia exige:

```text
raw_summary.bcch_row_count > 0
raw_summary.invalid_bcch_reference_count = 0
fx_summary.bcch_provider_count > 0
fx_summary.official_quality_count > 0
```

Las etiquetas diarias Yahoo se interpretan en la fecha calendario local del
proveedor antes de UTC, evitando convertir lunes BST en domingo. No se alteran
valores ni timestamps intradía.

## Prohibiciones

No reparar OHLC, no aumentar `MAX_INVALID_ROWS_PER_SERIES`, no reducir
`MIN_VALID_ROW_RATIO`, no usar `repair=True` para evidencia final, no etiquetar
un mirror como fuente oficial, no escribir en `acciones_dataset`, no desplegar,
no hacer merge y no llamar al broker.

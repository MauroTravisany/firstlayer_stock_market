# WP-02 — Snapshot, experiment registry y replay

## Estado operativo

Este runbook no autoriza despliegues ni ejecución productiva. Mientras los gates
posteriores permanezcan abiertos:

- Strategy Brain continúa pausado;
- los candidatos son `BACKTEST_ONLY`;
- `production_change_allowed` permanece en `FALSE`;
- Alpaca permanece Paper;
- `Deploy Cloud Run service` permanece deshabilitado hasta autorización separada.

## 1. Validar contratos en código

```bash
python scripts/ci/validate_data_contracts.py \
  --repo-root . \
  --contracts-dir contracts \
  --manifest contracts/manifest.json \
  --runtime-manifest cloud-functions/strategy_brain/contract_set_manifest.json
```

El comando debe terminar con exit code 0 y producir los mismos
`contract_set_hash` y `schema_snapshot_hash` versionados. Un cambio de contrato
requiere regenerar ambos manifests y explicar la migración.

## 2. Validar schemas observados

La exportación BigQuery es read-only y se realiza después de aplicar las tablas
del registry en un entorno controlado:

```bash
python scripts/ci/validate_observed_schemas.py \
  --contracts-dir contracts \
  --observed-schema /ruta/observed_schemas.json
```

No se permite convertir una discrepancia en warning. El schema observado debe
corregirse o el contrato debe versionarse mediante una PR separada.

## 3. Construir un snapshot

Preparar un manifest de fuentes con una fila por tabla/partición y su checksum
SHA-256. Después ejecutar:

```bash
python -m research.snapshot_manifest \
  --contracts-dir contracts \
  --source-manifest source_manifest.json \
  --source-cutoff 2026-08-10T23:59:59Z \
  --environment shadow \
  --created-by operador \
  --quality-report quality_report.json \
  --publish \
  --output snapshot.json
```

La publicación falla si el quality gate no es `PASS`. El registro publicado es
inmutable y debe insertarse en `audit_data_snapshots` antes de iniciar un
experimento.

## 4. Iniciar Strategy Brain

Una petición de generación debe incluir, como mínimo:

```json
{
  "phase": "generate",
  "attempt_id": "attempt-001",
  "data_snapshot_id": "snapshot_<sha256>",
  "universe_version": "megacap-tech-v1",
  "hypothesis": "Hipótesis concreta y falsable"
}
```

El adapter crea `experiment_id` y `run_id` antes de construir candidatos. Si el
snapshot no está publicado, es mutable, no supera calidad o no coincide con el
contract set, la petición falla cerrada.

## 5. Replay read-only

Exportar el bundle de experimento, snapshot, candidatos, artefactos y decisiones
y ejecutar:

```bash
python -m research.replay \
  --bundle experiment_bundle.json \
  --repo-root . \
  --output replay_plan.json
```

El replay no escribe BigQuery ni llama al broker. Rechaza drift de dependencias,
configuración, snapshot, lineage o checksums. Dos ejecuciones del mismo bundle
deben producir el mismo `replay_plan_checksum`.

## 6. Fallos y recuperación

- `REGISTRY_PENDING` no es consumible por Dataform.
- Un fallo parcial marca la corrida `FAILED`; no se reusa el mismo intento como
  si fuera una corrida limpia.
- Para reintentar, crear un nuevo `attempt_id`, conservando el
  `parent_experiment_id` cuando corresponda.
- No editar registros terminales. Toda corrección crea una nueva corrida o un
  nuevo snapshot.
- No eliminar evidencia huérfana; sirve para reconstruir el fallo.

## 7. Rollback

WP-02 es aditivo. El rollback operacional consiste en mantener Strategy Brain
pausado y dejar consumidores legacy intactos. Las tablas audit nuevas no se
borran. Si el adapter se deshabilita, ninguna nueva corrida se considera
promocionable y los resultados previos conservan `LEGACY_PRE_AUDIT_GRADE`.

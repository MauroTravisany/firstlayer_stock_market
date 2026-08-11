# WP-02 - Snapshot, experiment registry, and replay

## Operating state

This runbook does not authorize deployment or production execution. Strategy
Brain remains paused, candidates remain `BACKTEST_ONLY`, policy remains
`SHADOW_ONLY`, `production_change_allowed` remains false, Alpaca remains Paper,
and the Cloud Run deploy workflow remains disabled.

## 1. Verify the deployable entrypoint

Strategy Brain has one deployable path:

```text
Dockerfile -> CMD ["python", "main.py"]
main.py -> import legacy_main as legacy
main.py -> install(legacy)
main(request) -> legacy.main(request)
```

`legacy_main.py` preserves the historical implementation. Do not add a second
entrypoint or bypass `install(legacy)`. Both direct `python main.py` and
Functions Framework imports must therefore instrument the same module before a
request reaches `legacy.main`.

Safe verification:

```bash
docker build --tag wp02-strategybrain cloud-functions/strategy_brain
python scripts/ci/integration_test_containers.py \
  --image wp02-strategybrain \
  --service strategybrain
```

The result must show image, container, and process commands as
`["python", "main.py"]`, `registry_installed=true`, both generation/review
wrappers installed, `alternate_entrypoint_exists=false`, and
`mutation_performed=false`.

## 2. Validate contracts

```bash
python scripts/ci/validate_data_contracts.py \
  --repo-root . \
  --contracts-dir contracts \
  --manifest contracts/manifest.json \
  --runtime-manifest cloud-functions/strategy_brain/contract_set_manifest.json
```

The command must exit 0 and reproduce the versioned contract and schema hashes.
A contract change requires regenerated manifests and an explicit migration.

## 3. Validate observed schemas

This step is blocked until a separately authorized, read-only BigQuery schema
export is available:

```bash
python scripts/ci/validate_observed_schemas.py \
  --contracts-dir contracts \
  --observed-schema /path/to/observed_schemas.json
```

Schema mismatches are errors, not warnings. This PR does not query GCP.

## 4. Build and publish a shadow snapshot

After explicit authorization, prepare a source manifest containing one row per
table/partition and its SHA-256 checksum, then run:

```bash
python -m research.snapshot_manifest \
  --contracts-dir contracts \
  --source-manifest source_manifest.json \
  --source-cutoff 2026-08-10T23:59:59Z \
  --environment shadow \
  --created-by operator \
  --quality-report quality_report.json \
  --publish \
  --output snapshot.json
```

Publication fails unless the quality gate is `PASS`. A published snapshot is
immutable and must exist in `audit_data_snapshots` before an experiment starts.
No real snapshot is published by WP-02's PR.

## 5. Start a controlled shadow experiment

Only after separate authorization and while preserving `BACKTEST_ONLY`:

```json
{
  "phase": "generate",
  "attempt_id": "attempt-001",
  "data_snapshot_id": "snapshot_<sha256>",
  "universe_version": "megacap-tech-v1",
  "hypothesis": "Concrete, falsifiable hypothesis"
}
```

The adapter allocates `experiment_id` and `run_id` before it invokes candidate
generation. An absent, mutable, unpublished, failed-quality, or contract-drifted
snapshot fails closed. Strategy Brain remains paused during this PR.

## 6. Read-only replay

```bash
python -m research.replay \
  --bundle experiment_bundle.json \
  --repo-root . \
  --output replay_plan.json
```

Replay writes neither BigQuery nor broker state. It rejects dependency,
configuration, snapshot, lineage, and checksum drift. The same bundle must
produce the same `replay_plan_checksum`. Full economic replay is deferred to
WP-07.

## 7. Failure handling

- `REGISTRY_PENDING` is not consumable by Dataform.
- Partial failure marks the run `FAILED`; it is not reused as a clean run.
- Retry with a new `attempt_id`, retaining `parent_experiment_id` when needed.
- Never edit terminal records; create a new run or snapshot.
- Preserve orphaned evidence for failure reconstruction.

## 8. Rollback boundary

WP-02 is additive. Operational rollback means keeping Strategy Brain paused and
legacy consumers unchanged. Do not delete audit tables. If registry
instrumentation is unavailable, no new run is promotion-eligible and prior
results remain `LEGACY_PRE_AUDIT_GRADE`.

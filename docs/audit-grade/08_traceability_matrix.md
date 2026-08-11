# 08 — Matriz de trazabilidad

Esta matriz es la fuente de verdad para el avance. Los estados permitidos son:

```text
MISSING
PLANNED
IMPLEMENTED_UNVERIFIED
PARTIAL
PASS
FAIL
BLOCKED
```

Una fila solo pasa a `PASS` con enlace a código, prueba ejecutada y evidencia reproducible.

## 0. Baseline y resultados legacy

| ID | Requisito/invariante | Riesgo cubierto | WP | Implementación | Prueba ejecutada | Evidencia | Estado | Revisado |
|---|---|---|---|---|---|---|---|---|
| BASE-01 | Commit, configuración, Dataform, schedulers, servicios y resultados quedan inventariados | No poder reconstruir el estado previo | WP-00 | [`tools/capture_baseline.py`](../../tools/capture_baseline.py) | `python -m tools.capture_baseline --verify docs/audit-grade/evidence/baseline_manifest.json --strict` (exit 0) | [`baseline_manifest.json`](evidence/baseline_manifest.json), checksum `4e7dd4d04d90b79d28cc5852c514087dc6298a9a6d6e48191f58a98ad45644f2` | PASS | 2026-08-08 |
| BASE-02 | Capturas repetidas del mismo estado producen el mismo checksum | Drift o serialización no determinista | WP-00 | [`tools/capture_baseline.py`](../../tools/capture_baseline.py) | captura normal + captura con orden inverso (exit 0/0), checksum idéntico; `test_configuration_rows_with_duplicate_ids_are_canonicalized`; BigQuery `SINGLE_SYSTEM_TIME_AS_OF`; inventarios REST no transaccionales declarados | [`WP-00.md`](evidence/WP-00.md) | PASS | 2026-08-08 |
| BASE-03 | V1–V4, Strategy Brain y políticas tienen checksums y defectos conocidos | Resultados legacy confundidos con evidencia vigente | WP-00 | [`legacy_result_registry.sqlx`](../../dataform/definitions/legacy_result_registry.sqlx) estático, generado desde el manifest | Dataform compile: 219 acciones; BigQuery dry-run: 0 bytes (exit 0); `test_static_registry_matches_frozen_manifest` | [`baseline_manifest.json`](evidence/baseline_manifest.json) | PASS | 2026-08-08 |
| BASE-04 | Todo resultado legacy es `LEGACY_PRE_AUDIT_GRADE` y no promocionable | Promoción accidental de historia inválida | WP-00 | [`legacy_result_registry.sqlx`](../../dataform/definitions/legacy_result_registry.sqlx) assertions + manifest validator | `test_legacy_results_are_never_promotion_eligible`; `test_manifest_tampering_is_rejected` (exit 0) | [`WP-00.md`](evidence/WP-00.md) | PASS | 2026-08-08 |
| BASE-05 | Política permanece `SHADOW_ONLY`, Brain pausado o `LEGACY_RESEARCH`, cambios productivos falsos y Alpaca Paper | Habilitación accidental de ejecución | WP-00 | validación estructural + readiness fail-closed en [`tools/capture_baseline.py`](../../tools/capture_baseline.py) | pre-pausa `BASELINE_NOT_READY` (exit 3); post-pausa `BASELINE_READY` (exit 0); ambos schedulers leídos como `PAUSED`; `operational_blockers=[]` | [`baseline_manifest.json`](evidence/baseline_manifest.json) | PASS | 2026-08-08 |
| BASE-06 | La herramienta de captura no posee superficies de mutación operacional | Baseline que altera el estado observado | WP-00 | allowlist SQL/CLI y clientes HTTP GET en [`tools/capture_baseline.py`](../../tools/capture_baseline.py) | `test_only_read_only_cloud_and_bigquery_commands_are_allowed`; `test_git_tag_creation_and_deletion_are_rejected`; `test_bigquery_reader_rejects_mutation_before_client_call`; `test_cloud_inventory_uses_get_and_sanitizes_service_secrets` (exit 0) | [`WP-00.md`](evidence/WP-00.md) | PASS | 2026-08-08 |
| BASE-07 | Validez estructural no equivale a readiness operacional | Un blocker bien registrado no impide que `--verify` retorne éxito | WP-00 | `validate_manifest_structure` + `validate_manifest_readiness` y `--strict` en [`tools/capture_baseline.py`](../../tools/capture_baseline.py) | `test_structure_allows_a_registered_operational_blocker`; tests CLI structural/strict; pre-pausa exit 3 y post-pausa exit 0 | [`WP-00.md`](evidence/WP-00.md) | PASS | 2026-08-08 |
| BASE-08 | Fallback BigQuery solo se decide por metadata conocida | Permisos, SQL, timeout o red degradados silenciosamente a lectura live | WP-00 | clasificación `BASE TABLE`/`VIEW` en [`tools/capture_baseline.py`](../../tools/capture_baseline.py) | tests de VIEW, permiso, autenticación, SQL, timeout, red y error inesperado (exit 0); captura final `SINGLE_SYSTEM_TIME_AS_OF` | [`baseline_manifest.json`](evidence/baseline_manifest.json) | PASS | 2026-08-08 |

## 0.1 Contratos, snapshots y experiment registry

| ID | Requisito/invariante | Riesgo cubierto | WP | Implementación | Prueba ejecutada | Evidencia | Estado | Revisado |
|---|---|---|---|---|---|---|---|---|
| REG-01 | Contratos machine-readable comparten versión y hashes canónicos | Semántica tribal o manifests inconsistentes | WP-02 | [`contracts/`](../../contracts), [`data_contracts.py`](../../packages/common/data_contracts.py), [`validate_data_contracts.py`](../../scripts/ci/validate_data_contracts.py) | suite `tests/unit/wp02` + validator de manifests | [`WP-02.md`](evidence/WP-02.md) | IMPLEMENTED_UNVERIFIED | 2026-08-10 |
| REG-02 | Schema drift de tabla/columna/tipo/modo falla cerrado | Ejecutar sobre schemas incompatibles | WP-02 | [`validate_observed_schemas.py`](../../scripts/ci/validate_observed_schemas.py) | `test_observed_schema_cli`, `test_contracts` | [`WP-02.md`](evidence/WP-02.md) | IMPLEMENTED_UNVERIFIED | 2026-08-10 |
| REG-03 | Snapshot es content-addressed, quality-gated e inmutable | Experimento sin inputs congelados | WP-02 | [`data_snapshots.py`](../../packages/common/data_snapshots.py), [`snapshot_manifest.py`](../../research/snapshot_manifest.py), `audit_data_snapshots` | `test_snapshots`, tamper/quality/source-manifest fixtures | [`WP-02.md`](evidence/WP-02.md) | IMPLEMENTED_UNVERIFIED | 2026-08-10 |
| REG-04 | `experiment_id` existe antes de candidatos y config/dependencias tienen hash | Candidatos huérfanos o corrida irreproducible | WP-02 | [`experiment_identity.py`](../../cloud-functions/strategy_brain/experiment_identity.py), `audit_experiment_runs` | `test_strategy_brain_registry_contract`, `test_hashing` | [`WP-02.md`](evidence/WP-02.md) | IMPLEMENTED_UNVERIFIED | 2026-08-10 |
| REG-05 | IDs y claves compuestas aíslan experiment/run/candidate | Colisiones o contaminación cross-run | WP-02 | [`experiment_registry_storage.py`](../../cloud-functions/strategy_brain/experiment_registry_storage.py), `audit_experiment_candidates` | `test_strategy_brain_registry_storage`, `test_experiment_registry` | [`WP-02.md`](evidence/WP-02.md) | IMPLEMENTED_UNVERIFIED | 2026-08-10 |
| REG-06 | Conjunto incompleto no es visible ni publicable | Backtest sobre candidatos parcialmente persistidos | WP-02 | `REGISTRY_PENDING` + commit a `BACKTEST_ONLY`; [`trading_backtest_context_variants.sqlx`](../../dataform/definitions/trading_backtest_context_variants.sqlx); invariant assertion | `test_registry_wiring`, publicación incompleta | [`WP-02.md`](evidence/WP-02.md) | IMPLEMENTED_UNVERIFIED | 2026-08-10 |
| REG-07 | Artefactos/decisiones son inmutables, checksummed y sin autoridad productiva | Evidencia manipulada o auto-promoción | WP-02 | [`experiment_registry.py`](../../packages/common/experiment_registry.py), tablas artifacts/decisions | ID/checksum/tamper tests | [`WP-02.md`](evidence/WP-02.md) | IMPLEMENTED_UNVERIFIED | 2026-08-10 |
| REG-08 | Replay read-only valida snapshot, lineage, locks y checksums | Resultado imposible de reconstruir | WP-02 | [`research/replay.py`](../../research/replay.py) | `test_replay` determinism/dependency drift | [`WP-02.md`](evidence/WP-02.md) | IMPLEMENTED_UNVERIFIED | 2026-08-10 |

## 1. Datos point-in-time

| ID | Requisito/invariante | Riesgo actual | WP | Evidencia requerida | Estado inicial |
|---|---|---|---|---|---|
| PIT-01 | `available_at <= signal_timestamp` | Estados usan period end como disponibilidad | WP-03 | test de filing tardío + audit SQL con 0 violaciones | MISSING |
| PIT-02 | Fecha real de filing/publicación | `report_date` nulo | WP-03 | source adapter + contract + fixture | MISSING |
| PIT-03 | Revisiones/restatements versionadas | Historia puede sobrescribirse semánticamente | WP-03 | snapshot anterior reproducible | MISSING |
| PIT-04 | YoY sobre serie trimestral deduplicada | LAG se calcula tras join multiplicado | WP-03 | golden quarterly fixture | MISSING |
| PIT-05 | Earnings calendar y reported separados | Riesgo de retroactividad | WP-03 | event version tests | MISSING |
| PIT-06 | Macro vintage cuando es revisable | Valor actual puede contaminar historia | WP-03/07 | vintage contract/report | PLANNED |
| PIT-07 | Universo versionado | `universe_version` queda fijado en el experimento, pero aún falta membership PIT | WP-02/07 | registry + futura tabla de membresía | PARTIAL |

## 2. Precios y corporate actions

| ID | Requisito/invariante | Riesgo actual | WP | Evidencia requerida | Estado inicial |
|---|---|---|---|---|---|
| PX-01 | `source_interval` persistido | 1d/15m/4h no distinguibles | WP-04 | contract + rows | MISSING |
| PX-02 | No mezclar daily e intradía | Volumen/precios pueden duplicarse | WP-04 | golden duplicate fixture | MISSING |
| PX-03 | Raw para ejecución, adjusted para retornos | `auto_adjust=False` sin adjusted model | WP-04 | split/dividend tests | MISSING |
| PX-04 | Corporate actions PIT | No existe contrato completo | WP-04 | action table + reconciliation | MISSING |
| PX-05 | Calendario por exchange/DST | Sesiones inferidas por filas | WP-04/05 | holiday/DST tests | MISSING |
| PX-06 | Segunda fuente/reconciliación | Dependencia concentrada en Yahoo | WP-04 | mismatch report | MISSING |
| PX-07 | FX histórico para PnL CLP | USD/CLP fijo | WP-04/05 | FX PIT fixture | MISSING |

## 3. Backtesting

| ID | Requisito/invariante | Riesgo actual | WP | Evidencia requerida | Estado inicial |
|---|---|---|---|---|---|
| BT-01 | Entrada siguiente apertura | Implementado en motor direccional | WP-05 | regression test | IMPLEMENTED_UNVERIFIED |
| BT-02 | Gap-aware stop fill | Fill exacto en stop | WP-05 | gap fixture | MISSING |
| BT-03 | Ambigüedad stop/TP reportada | Stop-first sin sensitivity completa | WP-05 | count + sensitivity | PARTIAL |
| BT-04 | Time exit por sesiones | Corregido en parte | WP-05 | equity/crypto fixtures | IMPLEMENTED_UNVERIFIED |
| BT-05 | Capital inicial incluido en peak | Brain puede subestimar DD inicial | WP-05/06 | first-loss test | MISSING |
| BT-06 | Self-financing limita notional por equity | Notional fijo hasta capital inicial | WP-05 | cash invariant | MISSING |
| BT-07 | Fixed-notional etiquetado | Documentación parcial | WP-05 | model field/report | PARTIAL |
| BT-08 | No solapamiento one-slot | Implementación SQL existente | WP-05 | property/golden test | IMPLEMENTED_UNVERIFIED |
| BT-09 | Costos stress | Solo costo base | WP-05/07 | 1x/1.5x/2x report | MISSING |
| BT-10 | Benchmarks | No publicados | WP-05/07 | benchmark ledgers | MISSING |
| BT-11 | Ledger auditable/checksum | Registry de artefactos ya existe; ledger económico se implementa en WP-05 | WP-02/05 | immutable ledger | PARTIAL |

## 4. Strategy Brain

| ID | Requisito/invariante | Riesgo actual | WP | Evidencia requerida | Estado inicial |
|---|---|---|---|---|---|
| BR-01 | candidate ID globalmente único | Adapter genera `cand_<sha256>` con experiment/run/config; falta validación live | WP-02/06 | two-run test + live shadow | IMPLEMENTED_UNVERIFIED |
| BR-02 | Join aislado por run/experiment | Registry y variantes usan claves compuestas; otros modelos legacy se revisan en WP-06 | WP-02/06 | zero cross-run rows | PARTIAL |
| BR-03 | `best_eligible` controla decisión | Se usa best overall | WP-06 | divergent-candidates test | FAIL |
| BR-04 | Capital inicial en drawdown | Seed ausente | WP-05/06 | first-loss test | FAIL |
| BR-05 | Candidate budget explícito | Familias truncadas silenciosamente | WP-06 | expected family test | FAIL |
| BR-06 | Validation separada de test | Validation se reutiliza adaptativamente | WP-06/07 | locked-test access test | FAIL |
| BR-07 | Hypothesis count | Registry exige count exacto, índices únicos/contiguos y cobertura completa | WP-02/06/07 | registry/report | IMPLEMENTED_UNVERIFIED |
| BR-08 | Penalización multiple testing | No implementada | WP-07 | adjusted result | MISSING |
| BR-09 | Reducción de notional no simula alpha | Ranking puede premiarla | WP-06/07 | normalized-risk test | MISSING |
| BR-10 | IA no autoaprueba | IA entrega confidence/repetitions/status | WP-06/11 | mechanical evidence fields | FAIL |

## 5. Validación cuantitativa

| ID | Requisito/invariante | Riesgo actual | WP | Evidencia requerida | Estado inicial |
|---|---|---|---|---|---|
| QV-01 | Nested walk-forward | No existe framework completo | WP-07 | fold report | MISSING |
| QV-02 | Purging/embargo | No existe | WP-07 | overlap test | MISSING |
| QV-03 | Final locked test | No existe | WP-07 | permission/query test | MISSING |
| QV-04 | Intervalos/uncertainty | Umbrales puntuales | WP-07 | bootstrap report | MISSING |
| QV-05 | Multiple-testing adjustment | No existe | WP-07 | FDR/DSR/PBO evidence | MISSING |
| QV-06 | Benchmarks y excess return | No publicado | WP-07 | comparison report | MISSING |
| QV-07 | Estabilidad por fold/año/activo/régimen | Parcial | WP-07 | stability tables | MISSING |
| QV-08 | Sensibilidad parámetros vecinos | No existe | WP-07/12 | surface report | MISSING |
| QV-09 | Cost stress | No existe formalmente | WP-07 | stress report | MISSING |
| QV-10 | Resultado reproducible por ID | Skeleton replay valida IDs, snapshot y locks; falta replay cuantitativo completo | WP-02/07 | replay checksum | PARTIAL |

## 6. Executor y broker

| ID | Requisito/invariante | Riesgo actual | WP | Evidencia requerida | Estado inicial |
|---|---|---|---|---|---|
| EX-01 | Fallar cerrado si positions falla | Continúa con set vacío | WP-08 | failure test | FAIL |
| EX-02 | Límite recalculado por orden | Se valida una vez | WP-08 | loop limit test | FAIL |
| EX-03 | Notional inválido se rechaza | Fallback a máximo | WP-08 | numeric validation test | FAIL |
| EX-04 | Fecha real de envío para límite diario | Usa analysis_date | WP-08 | broker-day test | FAIL |
| EX-05 | Persist-before-send/outbox | Envía antes de persistir | WP-08 | timeout-after-accept test | FAIL |
| EX-06 | Retry reconciliado por client ID | Parcial | WP-08 | duplicate test | PARTIAL |
| EX-07 | Quote faltante/stale bloquea | Precio puede caer a cero en monitor | WP-08 | stale/missing tests | FAIL |
| EX-08 | Kill switches | No completo | WP-08 | switch tests | MISSING |
| EX-09 | Reconciliation findings | Parcial | WP-08/09 | report with zero critical | PARTIAL |
| EX-10 | Solo Alpaca Paper | Guard existente | WP-08 | config test | IMPLEMENTED_UNVERIFIED |
| EX-11 | Policy shadow bloquea entrada | Política actual shadow | WP-08 | invariant CI check | IMPLEMENTED_UNVERIFIED |

## 7. CI/CD, seguridad e infraestructura

| ID | Requisito/invariante | Riesgo actual | WP | Evidencia requerida | Estado actual |
|---|---|---|---|---|---|
| CI-01 | `main` única rama canónica | Default branch y ruleset `protect-main` ya están activos; `master` no despliega | WP-01 | lectura GitHub post-merge + workflow contracts | PASS |
| CI-02 | CI antes de deploy | El deploy versionado sólo consume un `workflow_run` exitoso de `CI` para el SHA exacto de un push a `main`; el workflow permanece deshabilitado hasta autorización | WP-01 | [contratos y arquitectura CI/CD](evidence/WP-01.md#arquitectura-resultante) | PASS |
| CI-03 | Tests cuantitativos en CI | CI ejecuta los tests Python existentes, pero la cobertura cuantitativa audit-grade completa pertenece a WP-05/WP-07 | WP-01/05/07 | [suite ejecutada](evidence/WP-01.md#verificación-ejecutada) | PARTIAL |
| CI-04 | Dataform test dataset/dry-run | Dataform compila de forma reproducible; aún no existe dataset aislado ni dry-run BigQuery para todas las acciones | WP-01/05 | [compilación Dataform](evidence/WP-01.md#verificación-ejecutada) | PARTIAL |
| CI-05 | Build once/promote digest | CI construye una vez, valida checksum e image ID y deploy exige el artefacto del run exacto y digest inmutable; no existe evidencia de promoción live porque deploy está deshabilitado | WP-01/10 | [artefactos inmutables y builds locales](evidence/WP-01.md#build-once-e-identidad) | PARTIAL |
| CI-06 | Environment approval | `production` existe y se limita a `main`; falta un segundo reviewer humano independiente | WP-01 | lectura GitHub environment/rules | PARTIAL |
| CI-07 | Invariantes de seguridad del repositorio | Riesgo de habilitar ejecución, reactivar Strategy Brain, desplegar ramas no autorizadas o promover legacy | WP-01 | [checker y pruebas negativas](evidence/WP-01.md#invariantes-de-seguridad) | PASS |
| CI-08 | Sintaxis y permisos mínimos de workflows | Riesgo de YAML inválido o permisos `write` innecesarios | WP-01 | [actionlint y contratos](evidence/WP-01.md#verificación-ejecutada) | PASS |
| CI-09 | Promoción Dataform auditada | Candidato exacto se compila sin mover producción; la rama productiva usa CAS y rollback de release+rama. No se ejecutó contra production | WP-01 | [promoción transaccional y pruebas](evidence/WP-01.md#promocion-dataform-transaccional-por-referencia) | PARTIAL |
| CI-10 | Dashboard sin SHA obsoleto | El workflow valida repositorio, evento, CI y SHA actual de `main`, y repite el check antes de Pages | WP-01 | [arquitectura y contratos](evidence/WP-01.md#arquitectura-resultante) | PASS |
| CI-11 | Dependencias críticas fail-closed | Audits separados; excepciones exactas exigen issue abierto, finding presente, unicidad y expiración. `vm2` se sigue en #52 | WP-01 | [gate y excepciones](evidence/WP-01.md#dependencias) | PASS |
| CI-12 | Smoke funcional no mutante | Liveness estático y readiness real con identidad, configuración, imports, secretos, tablas read-only y modos seguros; 8/8 imágenes integradas | WP-01/09 | [implementación y pruebas](evidence/WP-01.md#smoke-funcional-no-mutante) | PASS |
| CI-13 | Transición Dataform/Cloud Run compatible | No hay transacción distribuida; CI exige expansión aditiva que soporte consumidores legacy y current antes de Cloud Run | WP-01 | [contrato expand/contract](evidence/WP-01.md#contrato-expandcontract) | PASS |
| SEC-01 | Workload Identity Federation | JSON SA secret | WP-10 | OIDC workflow | MISSING |
| SEC-02 | Least privilege por servicio | Permisos no inventariados | WP-10 | IAM matrix | MISSING |
| SEC-03 | Terraform fuente de verdad | Infra parcial/dispersa | WP-10 | plan/drift report | MISSING |
| SEC-04 | Deletion protection/retention | Varias tablas sin protección | WP-10 | policy test | MISSING |
| SEC-05 | Entornos separados | Un proyecto/dataset principal | WP-10 | environment manifest | MISSING |
| SEC-06 | SBOM/vulnerability scan | No existe | WP-10 | CI artifact | MISSING |

## 8. Observabilidad y operación

| ID | Requisito/invariante | Riesgo actual | WP | Evidencia requerida | Estado inicial |
|---|---|---|---|---|---|
| OP-01 | Correlation IDs end-to-end | Parcial | WP-09 | trace example | MISSING |
| OP-02 | SLO/freshness/quality | Calidad parcial, SLO no formal | WP-09 | SLO dashboard | PARTIAL |
| OP-03 | Runbooks | Documentación parcial | WP-09/11 | drill evidence | PARTIAL |
| OP-04 | Backfill seguro | Manual/no estandarizado | WP-09 | backfill test | MISSING |
| OP-05 | Rollback probado | Restauración desde `spec.traffic` con post-describe de spec/status/tags/porcentajes y rollback Dataform release+rama probados; falta drill live autorizado | WP-01/09 | [rollback exacto](evidence/WP-01.md#rollback-exacto) | PARTIAL |
| OP-06 | RPO/RTO/restore | No definido | WP-10 | restore evidence | MISSING |
| OP-07 | Cost monitoring | No formal | WP-09 | budget/alert | MISSING |

## 9. Documentación y auditoría

| ID | Requisito/invariante | Riesgo actual | WP | Evidencia requerida | Estado inicial |
|---|---|---|---|---|---|
| DOC-01 | Docs fijadas a commit/snapshot | Repo documental sin vínculo completo | WP-11 | front matter | MISSING |
| DOC-02 | Auditorías current/superseded | M3/M4 describen diseño anterior | WP-11 | status markers | MISSING |
| DOC-03 | Catálogo generado desde contracts | Catálogo manual | WP-11 | generation check | MISSING |
| DOC-04 | ADRs | No formal | WP-11 | ADR index | MISSING |
| DOC-05 | Traceability evidence | Esta matriz inicia planificación | WP-11 | all critical rows PASS | PLANNED |
| DOC-06 | Changelog de semántica/resultados | Parcial | WP-11 | version log | MISSING |

## 10. Optimización por activo

| ID | Requisito/invariante | Riesgo actual | WP | Evidencia requerida | Estado inicial |
|---|---|---|---|---|---|
| OPT-01 | Optimizar solo tras gates | Riesgo de hacerlo antes | WP-12 | gate check | BLOCKED |
| OPT-02 | Modelo grupal antes de individual | No formal | WP-12 | hierarchy report | BLOCKED |
| OPT-03 | Shrinkage/regularización | No existe | WP-12 | coefficient report | BLOCKED |
| OPT-04 | Estabilidad de parámetros | No existe | WP-12 | neighborhood surface | BLOCKED |
| OPT-05 | OOS + stress + shadow/paper | No existe | WP-12 | promotion evidence | BLOCKED |

## 11. Regla de actualización

Cada PR debe modificar únicamente las filas que realmente cubre y añadir:

```text
Implementation: path/commit
Test: command/test name
Evidence: artifact/table/report
Reviewer verdict: PASS/PARTIAL/FAIL
Reviewed at: timestamp
```

No convertir `PLANNED` en `PASS` por haber escrito código sin ejecutar pruebas.

# 07 — Prompts de ejecución para Codex

Usar **un prompt por PR**, en orden. No ejecutar todos simultáneamente. Cada prompt presupone que el anterior fue revisado y fusionado.

## Prompt maestro para toda tarea

Copiar este encabezado antes del prompt específico:

```text
Trabaja en el repositorio MauroTravisany/firstlayer_stock_market.
Lee primero AGENTS.md y todos los documentos relevantes en docs/audit-grade/.
No despliegues, no fusiones, no cambies políticas a PAPER_CHAMPION o live y no modifiques recursos externos.
Crea una rama dedicada y una PR draft.
Mantén el scope estrictamente dentro del work package solicitado.
Antes de editar, inspecciona productores, consumidores, schemas, workflows y pruebas existentes.
Implementa en slices pequeños con pruebas de regresión.
Todo cambio de schema debe ser aditivo primero, con backfill, compatibilidad y rollback.
Ejecuta pruebas focalizadas y amplias. Incluye comandos, exit codes y resultados en la PR.
Actualiza docs/audit-grade/08_traceability_matrix.md con evidencia real; no marques PASS sin verificación.
Conserva SHADOW_ONLY, BACKTEST_ONLY y Alpaca Paper.
Si descubres un defecto adyacente, documéntalo pero no amplíes el scope sin autorización.
```

---

## Codex 00 — Baseline

```text
Implementa WP-00 de docs/audit-grade/06_implementation_backlog.md.

Resultado requerido:
- script read-only tools/capture_baseline.py;
- manifest versionado de ejemplo;
- definición Dataform legacy_result_registry;
- captura de versiones/configuraciones sin secretos;
- etiquetas explícitas LEGACY_PRE_AUDIT_GRADE y promotion_eligible=false;
- pruebas de determinismo y no mutación.

No recalcules ni cambies estrategias. No borres historia. No despliegues.
```

## Codex 01 — Gobierno y CI

```text
Implementa WP-01.

Resultado requerido:
- crear .github/workflows/ci.yml;
- separar completamente CI y deploy;
- deploy.yml solo puede desplegar desde main después de CI exitoso y environment approval;
- remover master de triggers de deploy;
- añadir CODEOWNERS, Dependabot y repo invariant check;
- incluir compileall, unit tests, contract tests, Dataform compile, dashboard build y Terraform validation;
- crear smoke-test script sin mutar producción;
- agregar una prueba/guard que falle si alguna policy ejecutable se habilita accidentalmente.

No cambies la default branch mediante código; documenta el paso manual de GitHub Settings en la PR.
```

## Codex 02 — Contratos y experiment registry

```text
Implementa WP-02.

Resultado requerido:
- contratos YAML para las tablas críticas actuales;
- validador de contratos;
- hashing canónico de configuración;
- tablas audit_data_snapshots, audit_experiment_runs, audit_experiment_candidates, audit_experiment_artifacts y audit_experiment_decisions;
- experiment_id creado antes de candidatos;
- IDs globalmente únicos;
- skeleton de research/replay.py;
- pruebas de schema drift, hashes e IDs.

No migres aún fundamentales o precios; crea la infraestructura compatible.
```

## Codex 03 — Point-in-time financiero

```text
Implementa WP-03 y cumple docs/audit-grade/02_data_contracts_and_point_in_time.md.

Primero crea fixtures que demuestren el look-ahead actual y el error del revenue_yoy. Luego implementa:
- fuente de filing timestamp verificable;
- financial_statements_pit y earnings_events_pit;
- available_at/revision/source metadata;
- cálculo YoY sobre la serie trimestral deduplicada antes del join diario;
- joins as-of por available_at <= signal_timestamp;
- audit_no_lookahead;
- dual-run y reporte de diferencias legacy vs PIT;
- feature flag de migración.

No uses period_end_date como fallback elegible. Un dato sin available_at verificable debe quedar degradado y excluido del backtest PIT.
```

## Codex 04 — Precios y corporate actions

```text
Implementa WP-04.

Primero crea fixtures de split, dividendo, 1d+15m duplicado, sesión incompleta, DST, gap y cripto 24/7.
Luego implementa:
- raw append-only con ingestion_run_id/source_interval/timezone/hash;
- corporate_actions_pit;
- market_price_canonical;
- selección canónica que nunca sume daily e intradía;
- raw OHLC para ejecución y adjusted close para retornos;
- calendario de sesiones;
- reconciliación con segunda fuente mediante adapter configurable;
- trading_price_features sobre la serie canónica;
- feature flag y dual-run.

No sustituyas silenciosamente la semántica de la tabla legacy.
```

## Codex 05 — Backtest auditable

```text
Implementa WP-05.

Crea primero golden tests con resultados calculados manualmente.
Implementa:
- execution_model_version y cost_model_version;
- siguiente apertura;
- fills gap-aware;
- conteo y sensitivity de velas ambiguas;
- time exits por sesiones;
- costos base/1.5x/2x;
- FIXED_NOTIONAL_EXPERIMENT y SELF_FINANCING_PORTFOLIO;
- seed de capital inicial para drawdown;
- limitación por equity en self-financing;
- trade ledger, equity curves, benchmarks e invariant audit;
- recalcular V1–V4 como nueva versión sin borrar legacy.

Toda métrica debe poder trazarse al ledger.
```

## Codex 06 — Strategy Brain

```text
Implementa WP-06.

Añade pruebas que fallen por:
- colisión de candidate_id entre corridas del mismo día;
- join sin run_id;
- best overall no elegible;
- drawdown del primer trade;
- truncamiento silencioso de familias.

Después corrige:
- IDs SHA256 con experiment_id;
- claves compuestas en todas las tablas;
- best_eligible;
- capital inicial;
- presupuesto de candidatos explícito;
- hypothesis_count;
- inner validation/outer test;
- prohibición técnica de leer test durante tuning;
- penalización por reducir notional sin mejorar alpha;
- IA solo como hipótesis estructurada no vinculante.

Mantén el scheduler deshabilitado o legacy-only hasta verificar todo.
```

## Codex 07 — Validación cuantitativa

```text
Implementa WP-07 siguiendo docs/audit-grade/03_quant_validation_standard.md.

Construye un job/servicio quant_validation que lea ledgers inmutables y produzca:
- nested walk-forward;
- purging y embargo;
- benchmarks;
- métricas completas;
- block bootstrap con seed;
- intervalos de confianza;
- hypothesis count y multiple-testing adjustments;
- análisis por fold/año/activo/régimen;
- sensitivity a costos y parámetros vecinos;
- reporte JSON/Markdown con checksums;
- decision gate mecánico y aprobación humana separada.

El tuner no debe tener acceso al final locked test. Demuéstralo con pruebas y permisos/contratos.
```

## Codex 08 — Executor seguro

```text
Implementa WP-08 y docs/audit-grade/04_execution_safety_standard.md.

Primero construye un fake broker stateful y regression tests para todos los fallos críticos.
Luego implementa:
- order_intents state machine/outbox;
- persist-before-send;
- idempotencia estable;
- fail-closed en cuenta, posiciones, órdenes, clock y quote;
- rechazo de notional inválido;
- límites recalculados antes de cada orden;
- broker submission date;
- quote freshness/spread gates;
- reconciliación por client_order_id ante timeout;
- kill switches;
- risk snapshots;
- monitor sin fallback de precio a cero;
- reconciliation findings y alertas.

No habilites PAPER_CHAMPION. Las pruebas Alpaca Paper reales deben ser controladas, separadas y no ejecutarse en PR sin secrets/approval.
```

## Codex 09 — Observabilidad

```text
Implementa WP-09.

Resultado requerido:
- structured logs con correlation IDs;
- métricas y SLOs por dominio;
- dashboards/alert policies como código;
- health/readiness;
- dependency freshness gate;
- runbooks y plantillas de incident/postmortem;
- prueba de backfill y rollback;
- scheduler dependency map;
- evidencia de que un fallo material pausa señales/entradas cuando corresponde.
```

## Codex 10 — Seguridad e infraestructura

```text
Implementa WP-10 en varias PRs pequeñas si es necesario, manteniendo un único epic.

Resultado requerido:
- Terraform como fuente de verdad para Cloud Run, Scheduler, Dataform, BigQuery, IAM, secrets y monitoring;
- service accounts por función;
- Workload Identity Federation;
- deletion protection/retention;
- entornos separados;
- Artifact Registry por digest, SBOM y scan;
- policy checks;
- threat model;
- dashboard público revisado/autenticado;
- RPO/RTO y restore test.

No apliques Terraform a producción sin aprobación separada. Entrega plan y pruebas en staging primero.
```

## Codex 11 — Documentación auditada

```text
Implementa WP-11.

Resultado requerido:
- front matter con status/system_commit/data_snapshot/reviewed_at;
- marcar auditorías históricas superseded cuando corresponda;
- ADRs;
- catálogo generado desde contracts;
- lineage y runbook index;
- changelog de modelos/resultados;
- CI que detecte documentación/contratos desactualizados;
- traceability matrix completa con enlaces a pruebas y artefactos.
```

## Codex 12 — Optimización por activo

```text
Solo ejecutar si WP-00 a WP-11 están aprobados.
Implementa el framework de docs/audit-grade/12_per_asset_optimization_protocol.md.

No optimices directamente cada ticker con pocos trades. Implementa primero modelos grupales y shrinkage jerárquico, restricciones, regularización, nested walk-forward y stability tests. La IA puede proponer hipótesis, pero no elegir parámetros finales.

Cada candidato debe superar baseline en outer test, costos stress y shadow/paper según gates. Si no hay evidencia, conservar la fórmula simple/grupal.
```

---

## Prompt de verificación independiente después de cada PR

```text
Realiza una revisión independiente y read-only de esta PR contra AGENTS.md y el work package correspondiente.
No corrijas código.
Construye una matriz requisito -> comportamiento -> prueba -> resultado.
Inspecciona tests antes de confiar en ellos.
Ejecuta checks focalizados y amplios disponibles.
Clasifica findings por severidad y confianza.
Emite PASS solo si todos los criterios materiales tienen evidencia fresca; en otro caso usa PARTIAL, FAIL o INCONCLUSIVE.
```

## Prompt final de release readiness

```text
Audita el repositorio completo contra docs/audit-grade/11_scorecard_10_of_10.md y 09_release_and_promotion_gates.md.
No uses las afirmaciones de la documentación como evidencia; verifica código, tests, CI, schemas, manifests y artefactos.
No habilites ninguna política.
Entrega score por dimensión, gaps, evidencia, comandos, riesgos residuales y veredicto sobre: research, shadow, paper y live.
```

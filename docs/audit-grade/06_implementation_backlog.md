# 06 — Backlog de implementación

Este documento es la secuencia obligatoria de cambios. Cada work package se implementa en una PR independiente. No mezclar P0 cuantitativo con optimización de fórmulas.

## Convenciones

- **P0:** bloquea confianza en resultados o seguridad.
- **P1:** requerido para operación sostenida y auditabilidad.
- **P2:** optimización posterior.
- **DoD:** Definition of Done verificable.
- Toda PR mantiene `SHADOW_ONLY` y no despliega live.

---

# WP-00 — Congelamiento y baseline reproducible

Prioridad: **P0**  
Dependencias: ninguna

## Objetivo

Preservar el estado anterior, registrar qué resultados son legacy y crear una base contra la cual comparar cambios.

## Tareas

1. Crear un tag o release `legacy-pre-audit-grade-2026-08` apuntando al commit base.
2. Exportar configuración efectiva de:
   - watchlist;
   - strategy versions;
   - active strategy config;
   - champion/challenger policy;
   - schedulers;
   - servicios Cloud Run;
   - Dataform release.
3. Registrar tablas y checksums de resultados V1–V4, Strategy Brain y señales actuales.
4. Crear tabla `legacy_result_registry` con:
   - result family;
   - source table;
   - date range;
   - git SHA;
   - data snapshot approximation;
   - known defects;
   - `promotion_eligible = FALSE`.
5. Confirmar que toda política está `SHADOW_ONLY`.
6. Pausar generación adaptativa del Strategy Brain mientras se implementan WP-03 a WP-07 o ejecutar únicamente con estado `LEGACY_RESEARCH`.
7. Añadir un script read-only `tools/capture_baseline.py`.

## Archivos esperados

```text
tools/capture_baseline.py
docs/audit-grade/evidence/baseline_manifest.example.json
dataform/definitions/legacy_result_registry.sqlx
```

## Pruebas

- captura repetida produce mismo checksum si no cambió el estado;
- el script no modifica tablas operativas;
- ningún resultado legacy queda elegible.

## DoD

Existe un manifest reproducible y los resultados antiguos están claramente separados.

## Rollback

No aplica; es aditivo y read-only.

---

# WP-01 — Gobierno de ramas y CI antes de deploy

Prioridad: **P0**  
Dependencias: WP-00

## Objetivo

Impedir que código no verificado o una rama antigua despliegue servicios.

## Tareas

1. Cambiar la rama predeterminada a `main` en GitHub.
2. Reconciliar `master`; luego bloquearla o eliminarla después de respaldo.
3. Modificar `.github/workflows/deploy.yml` para activarse solo por:
   - `workflow_run` exitoso de CI sobre `main`, o
   - `workflow_dispatch` con environment approval.
4. Crear `.github/workflows/ci.yml`.
5. Añadir `.github/CODEOWNERS`.
6. Configurar required checks y branch protection.
7. Añadir secret scan, dependency scan, Python tests, Dataform compile, dashboard build y Terraform validate.
8. Migrar autenticación futura a Workload Identity Federation; mientras no esté lista, limitar el secret actual solo al job deploy.
9. Dividir build de imagen y deploy: construir una vez y promover por digest.
10. Añadir smoke tests y rollback post-deploy.

## Archivos esperados

```text
.github/workflows/ci.yml
.github/workflows/deploy.yml
.github/CODEOWNERS
.github/dependabot.yml
scripts/ci/verify_repo_invariants.py
scripts/ci/smoke_test_services.py
```

## Pruebas

- PR no puede desplegar;
- push a `master` no despliega;
- CI falla si policy cambia a ejecución;
- deploy usa SHA/digest aprobado;
- smoke failure ejecuta rollback o detiene promoción.

## DoD

No existe camino de deploy que evite CI y aprobación.

## Rollback

Revertir workflow; conservar `main` como rama canónica.

---

# WP-02 — Contratos de datos y experiment registry

Prioridad: **P0**  
Dependencias: WP-01

## Objetivo

Crear contratos legibles por máquina, versionar datasets y hacer que cada experimento sea una unidad aislada.

## Tareas

1. Crear `contracts/` con YAML por tabla crítica.
2. Crear un validador Python de contratos.
3. Crear tablas:
   - `data_snapshots`;
   - `experiment_runs`;
   - `experiment_candidates`;
   - `experiment_artifacts`;
   - `experiment_decisions`.
4. Generar `configuration_hash`, `dependency_lock_hash` y checksums.
5. Eliminar hardcodes de proyecto/dataset en nuevos modelos mediante variables Dataform.
6. Introducir `environment`, `data_contract_version`, `feature_set_version`, `execution_model_version` y `cost_model_version`.
7. Hacer que Strategy Brain cree `experiment_id` antes de candidatos.
8. Añadir unique keys compuestas por corrida.
9. Crear comando de reproducción skeleton.

## Archivos esperados

```text
contracts/*.yaml
packages/common/data_contracts.py
packages/common/hashing.py
research/replay.py
dataform/definitions/audit_data_snapshots.sqlx
dataform/definitions/audit_experiment_runs.sqlx
dataform/definitions/audit_experiment_candidates.sqlx
dataform/definitions/audit_experiment_artifacts.sqlx
dataform/definitions/audit_experiment_decisions.sqlx
```

## Pruebas

- schema drift detectado;
- same config -> same hash;
- different run -> unique candidate IDs;
- experiment incompleto no puede publicarse;
- reproducción rechaza snapshot/config inconsistentes.

## DoD

Toda nueva corrida posee identidad, configuración y lineage inmutables.

## Rollback

Tablas aditivas; consumidores legacy permanecen hasta migración.

---

# WP-03 — Fundamentales y earnings point-in-time

Prioridad: **P0 crítico**  
Dependencias: WP-02

## Objetivo

Eliminar look-ahead y corregir cálculos financieros históricos.

## Tareas

1. Implementar productor de filings con timestamp verificable:
   - SEC submissions/companyfacts para emisores US;
   - IR/proveedor verificable para otros mercados;
   - mapping ticker/CIK versionado.
2. Guardar `filing_date`, `source_published_at`, `available_at`, `revision`, `form_type`.
3. Crear `financial_statements_pit` y `earnings_events_pit`.
4. Marcar filas sin disponibilidad verificable como no elegibles para backtest.
5. Reescribir `trading_historical_context.sqlx`:
   - deduplicar estados por periodo;
   - calcular YoY en serie trimestral;
   - join as-of con `available_at`.
6. Reescribir `portfolio_valuation_daily.sqlx` para usar ratios/estados PIT.
7. Separar calendario esperado de resultado reportado.
8. Añadir report de no-look-ahead.
9. Backfill y comparación contra legacy.
10. Invalidar métricas contextuales antiguas.

## Archivos actuales a modificar

```text
cloud-functions/financial_data/custom_function/data_processing.py
cloud-functions/financial_data/custom_function/bq_operations.py
cloud-functions/financial_data/main.py
cloud-functions/macro_data/custom_function/data_sources.py
cloud-functions/macro_data/custom_function/bq_operations.py
dataform/definitions/trading_historical_context.sqlx
dataform/definitions/portfolio_valuation_daily.sqlx
dataform/definitions/trading_earnings_context.sqlx
```

## Archivos nuevos sugeridos

```text
cloud-functions/financial_data/custom_function/sec_source.py
cloud-functions/financial_data/custom_function/point_in_time.py
dataform/definitions/financial_statements_pit.sqlx
dataform/definitions/earnings_events_pit.sqlx
dataform/definitions/audit_no_lookahead.sqlx
```

## Pruebas

- filing 31/03 publicado 02/05 no aparece el 01/05;
- aparece desde 02/05 o siguiente instante permitido;
- restatement no reescribe snapshot anterior;
- YoY usa trimestre equivalente real;
- ratio derivado indica statement y price timestamp;
- `available_at` futuro causa assertion failure.

## DoD

Cero uso de estados/earnings antes de disponibilidad y YoY validado independientemente.

## Rollback

Feature flag `USE_PIT_FINANCIALS`; mantener legacy solo para comparación, nunca promoción.

---

# WP-04 — Precios, corporate actions y granularidad canónica

Prioridad: **P0 crítico**  
Dependencias: WP-02

## Objetivo

Construir series raw/adjusted auditables sin mezcla 1d/intradía.

## Tareas

1. Añadir a ingesta:
   - `ingestion_run_id`;
   - `source_interval`;
   - `source_timezone`;
   - `exchange`;
   - `source_version`;
   - `payload_hash`.
2. Crear raw append-only; dejar de depender de overwrite semántico para historia.
3. Ingerir corporate actions.
4. Crear `market_price_canonical` con regla de selección por cobertura.
5. Separar raw OHLC de adjusted close.
6. Incorporar calendario de sesiones por exchange.
7. Reconciliar precios con segunda fuente para universo activo.
8. Crear alertas de mismatch y sesiones incompletas.
9. Reescribir `trading_price_features.sqlx` sobre la serie canónica.
10. Recalcular retornos, medias y volatilidad con adjusted close; mantener niveles de ejecución raw.
11. Añadir USD/CLP PIT cuando se reporta PnL CLP.

## Archivos actuales a modificar

```text
cloud-functions/daily_stocks/custom_function/data_processing.py
cloud-functions/daily_stocks/custom_function/bq_operations.py
cloud-functions/daily_stocks/main.py
dataform/definitions/trading_price_features.sqlx
dataform/definitions/portfolio_valuation_daily.sqlx
terraform/main.tf
```

## Archivos nuevos sugeridos

```text
cloud-functions/corporate_actions/
packages/common/market_calendar.py
dataform/definitions/market_price_canonical.sqlx
dataform/definitions/corporate_actions_pit.sqlx
dataform/definitions/audit_price_source_reconciliation.sqlx
dataform/definitions/fx_rates_pit.sqlx
```

## Pruebas

- split/dividendo;
- 1d + 15m no duplica volumen;
- intradía incompleto cae a daily con razón;
- DST/feriado;
- cripto UTC/4h;
- mismatch de fuente bloquea calidad;
- same raw snapshot produce same canonical checksum.

## DoD

Serie canónica sin ambigüedad y retornos reconciliados.

## Rollback

Feature flag `USE_CANONICAL_PRICES`; conservar tablas legacy read-only.

---

# WP-05 — Motor de backtest realista y capital

Prioridad: **P0 crítico**  
Dependencias: WP-03, WP-04

## Objetivo

Eliminar optimismo de fills, corregir drawdown/capital y producir un ledger auditable.

## Tareas

1. Versionar `execution_model_version` y `cost_model_version`.
2. Implementar entrada en siguiente sesión.
3. Implementar gap-aware stops/targets.
4. Registrar ambigüedad stop/TP y escenarios sensitivity.
5. Contar holding por sesiones.
6. Incorporar costos base/1.5x/2x.
7. Crear dos modelos:
   - fixed notional;
   - self-financing.
8. Incluir capital inicial en running peak.
9. Limitar notional por equity en self-financing.
10. Añadir benchmark ledgers.
11. Producir trade ledger inmutable con reason codes.
12. Añadir validaciones de no solapamiento y cash.
13. Recalcular V1–V4; marcar resultados anteriores legacy.

## Archivos actuales a modificar

```text
dataform/definitions/trading_directional_trade_results.sqlx
dataform/definitions/trading_directional_strategy_backtest.sqlx
dataform/definitions/trading_directional_strategy_daily_summary.sqlx
dataform/definitions/trading_contextual_backtest_results.sqlx
dataform/definitions/trading_brain_candidate_capital_curve.sqlx
dataform/definitions/trading_brain_candidate_summary.sqlx
```

## Archivos nuevos sugeridos

```text
dataform/definitions/backtest_execution_events.sqlx
dataform/definitions/backtest_trade_ledger.sqlx
dataform/definitions/backtest_equity_curves.sqlx
dataform/definitions/backtest_benchmarks.sqlx
dataform/definitions/backtest_invariant_audit.sqlx
```

## Pruebas

- gap bajo stop usa apertura adversa;
- primer trade perdedor genera drawdown;
- one-slot no solapa;
- self-financing no gasta más equity;
- fixed notional se etiqueta correctamente;
- costos stress reducen retorno;
- time exit usa sesiones;
- stop/TP ambiguous queda contado.

## DoD

Ledger, equity y métricas reproducibles, con invariantes verdes.

## Rollback

Mantener `execution_model_version`; comparar sin sobrescribir.

---

# WP-06 — Strategy Brain aislado y correcto

Prioridad: **P0 crítico**  
Dependencias: WP-02, WP-05

## Objetivo

Eliminar contaminación entre corridas y separar tuning de evaluación final.

## Tareas

1. Reemplazar IDs truncados por SHA256 completo de corrida/configuración.
2. Propagar `experiment_id/run_id` en variantes, resultados, curvas y summaries.
3. Corregir joins para usar clave compuesta.
4. Implementar `best_eligible` separado de `best_overall`.
5. Incluir seed de capital inicial.
6. Corregir presupuesto de candidatos; no truncar familias silenciosamente.
7. Registrar `hypothesis_count` por corrida y acumulado.
8. Separar inner validation y outer test.
9. Prohibir leer test durante generación/selección.
10. Penalizar reducción de notional que no mejora retorno por unidad de riesgo.
11. Convertir IA a hipótesis estructurada no vinculante.
12. Deduplicar auditorías por ID único/state transition.
13. Añadir convergencia reproducible y reason codes.

## Archivos actuales a modificar

```text
cloud-functions/strategy_brain/main.py
cloud-functions/strategy_brain/conf/conf.py
dataform/definitions/trading_backtest_context_variants.sqlx
dataform/definitions/trading_contextual_backtest_results.sqlx
dataform/definitions/trading_brain_candidate_capital_curve.sqlx
dataform/definitions/trading_brain_candidate_summary.sqlx
dataform/definitions/trading_brain_component_attribution.sqlx
```

## Pruebas

- dos corridas en el mismo minuto no colisionan;
- una variante solo lee su corrida;
- candidato overall rechazado no controla promoción;
- test query bloqueada durante tuning;
- candidate family completa;
- misma corrida/snapshot -> mismo resultado;
- lower notional sin alpha no gana ranking.

## DoD

Cada generación es aislada, reproducible y estadísticamente bien ubicada.

## Rollback

Deshabilitar scheduler y conservar nueva evidencia; no volver a IDs legacy.

---

# WP-07 — Framework de validación, benchmarks y reporte

Prioridad: **P0**  
Dependencias: WP-03 a WP-06

## Objetivo

Producir evidencia fuera de muestra con incertidumbre y múltiples pruebas.

## Tareas

1. Crear servicio/job `quant_validation`.
2. Implementar nested walk-forward con purging/embargo.
3. Implementar benchmarks.
4. Calcular métricas completas.
5. Implementar block bootstrap e intervalos.
6. Registrar hypothesis count y aplicar FDR/DSR/PBO cuando corresponda.
7. Reportar por fold/año/activo/régimen.
8. Ejecutar sensitivity de costos y parámetros vecinos.
9. Crear final locked test con permisos que impidan consulta durante tuning.
10. Generar reportes JSON/Markdown y checksums.
11. Crear decision gate mecánico + aprobación humana.
12. Publicar dashboard de evidencia, no solo PnL.

## Archivos nuevos sugeridos

```text
cloud-functions/quant_validation/
research/validation/
research/metrics/
research/statistics/
research/benchmarks/
dataform/definitions/validation_folds.sqlx
dataform/definitions/validation_benchmark_results.sqlx
dataform/definitions/validation_statistical_results.sqlx
dataform/definitions/validation_decisions.sqlx
```

## Pruebas

- folds sin leakage;
- embargo correcto;
- métricas contra cálculo manual;
- bootstrap determinístico con seed;
- test no accesible a tuner;
- multiple-testing penalty aumenta con hipótesis;
- benchmark fixtures correctos.

## DoD

Cada candidata tiene reporte OOS reproducible y clasificación de evidencia.

## Rollback

Job read-only sobre ledgers; no afecta señales.

---

# WP-08 — Executor outbox, risk gate y reconciliación

Prioridad: **P0 seguridad**  
Dependencias: WP-01, WP-02

## Objetivo

Garantizar que Paper falla cerrado, no duplica órdenes y siempre reconcilia.

## Tareas

1. Crear `order_intents` y state machine.
2. Persistir intención antes de llamar al broker.
3. Implementar adapter/fake broker.
4. Rechazar notional inválido.
5. Fallar cerrado en cuenta/posiciones/órdenes/clock/quote.
6. Recalcular límites antes de cada orden.
7. Contar órdenes por broker submission date.
8. Implementar quote freshness y spread gate.
9. Reconciliar timeout por `client_order_id`.
10. Crear kill switches.
11. Añadir snapshots de riesgo.
12. Corregir monitor para no usar precio cero.
13. Crear reporte de reconciliación y alertas.
14. Mantener política `SHADOW_ONLY` hasta gate.

## Archivos actuales a modificar

```text
cloud-functions/paper_trade_executor/main.py
cloud-functions/paper_trade_executor/custom_function/bq_operations.py
cloud-functions/paper_trade_executor/custom_function/alpaca_client.py
cloud-functions/paper_trade_executor/conf/conf.py
cloud-functions/paper_trade_risk_monitor/main.py
cloud-functions/paper_trade_risk_monitor/custom_function/bq_operations.py
cloud-functions/paper_trade_risk_monitor/custom_function/alpaca_client.py
```

## Archivos nuevos sugeridos

```text
packages/execution/state_machine.py
packages/execution/risk_gate.py
packages/execution/broker.py
packages/execution/fake_broker.py
dataform/definitions/paper_order_intents.sqlx
dataform/definitions/paper_reconciliation_findings.sqlx
dataform/definitions/paper_kill_switch_state.sqlx
```

## Pruebas

Todas las listadas en `04_execution_safety_standard.md`.

## DoD

No existe camino conocido para duplicar orden o enviar ante estado desconocido.

## Rollback

Deshabilitar schedulers; outbox conserva intenciones; reconciliar manualmente.

---

# WP-09 — Observabilidad, SLO y runbooks

Prioridad: **P1**  
Dependencias: WP-02, WP-08

## Objetivo

Detectar degradaciones antes de que contaminen señales o ejecución.

## Tareas

1. Structured logging con correlation IDs.
2. Métricas por ingesta, Dataform, señales, executor y reconciliación.
3. SLOs y error budgets.
4. Dashboards Cloud Monitoring.
5. Alertas por freshness, quality, mismatch, failures, lag y cost.
6. Runbooks de incidentes/backfill/rollback.
7. Tabla de incidentes y postmortems.
8. Health/readiness endpoints.
9. Scheduler dependency graph y freshness gate.
10. Pruebas de disaster recovery.

## DoD

Todo fallo material tiene señal, owner, runbook y evidencia de recuperación.

---

# WP-10 — Seguridad, IAM, secretos, infraestructura y entornos

Prioridad: **P1**  
Dependencias: WP-01

## Objetivo

Reducir blast radius y eliminar configuración manual no auditada.

## Tareas

1. Completar Terraform para Cloud Run, Scheduler, Dataform, BigQuery, IAM, secrets y monitoring.
2. Service account por responsabilidad.
3. Workload Identity Federation para GitHub.
4. Secret rotation y least privilege.
5. Deletion protection en tablas críticas.
6. Datasets/proyectos por entorno.
7. VPC/egress policy si aplica.
8. Artifact Registry con scan/SBOM.
9. Policy checks en CI.
10. Backup/retention/RPO/RTO.
11. Public dashboard revisado o autenticado.
12. Threat model.

## DoD

Infraestructura reproducible, permisos mínimos y drift visible.

---

# WP-11 — Documentación y auditoría continua

Prioridad: **P1**  
Dependencias: todos los anteriores

## Objetivo

Evitar que documentos y código vuelvan a divergir.

## Tareas

1. Front matter en documentos con commit/snapshot/status.
2. Marcar M1–M4 como current/superseded.
3. ADRs para decisiones cuantitativas y operativas.
4. Generar catálogo de tablas desde contratos.
5. Generar lineage y runbook index.
6. Changelog de modelos/resultados.
7. Linkear evidencia desde traceability matrix.
8. CI falla ante docs/contracts desactualizados.
9. Crear reporte de auditoría periódico.

## DoD

Una auditoría independiente encuentra fuente, código, prueba y evidencia sin conocimiento tribal.

---

# WP-12 — Optimización matemática por grupo y activo

Prioridad: **P2**  
Dependencias: WP-00 a WP-11 aprobados

## Objetivo

Optimizar reglas únicamente después de confiar en datos y evaluación.

## Tareas

Definidas en `12_per_asset_optimization_protocol.md`.

## DoD

Cada fórmula optimizada supera baseline en evidencia OOS, robustez y paper; de lo contrario se conserva la fórmula grupal/simple.

---

# Definition of Done global

El programa está implementado cuando:

- todos los P0 y P1 tienen PR y evidencia;
- traceability matrix no tiene filas críticas `MISSING`;
- CI y deploy están separados;
- datos PIT y precios canónicos están activos;
- backtest es determinístico y realista;
- Strategy Brain está aislado;
- executor Paper pasa pruebas y reconciliación;
- shadow/paper gates están aplicados;
- resultados legacy están separados;
- se puede reproducir una decisión completa por ID;
- la optimización por activo aún no se confunde con seguridad o validez.
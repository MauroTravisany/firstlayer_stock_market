# Programa de Transformación Audit-Grade

Estado: **especificación de implementación**  
Rama base auditada: `main` @ `fcd625acdba481940e24e80313ad73889e2d693d`  
Estado operativo obligatorio durante el programa: **SHADOW_ONLY / BACKTEST_ONLY / ALPACA PAPER**

## 1. Propósito

Este programa transforma `firstlayer_stock_market` desde una plataforma personal de investigación con controles parciales hacia una plataforma cuantitativa auditable, reproducible y operativamente segura.

El objetivo no es afirmar que todas las dimensiones son 10/10. El objetivo es definir qué evidencia objetiva debe existir para poder asignar esa evaluación. Una dimensión solo alcanza 10/10 cuando sus criterios de aceptación están implementados, verificados y trazados.

## 2. Definición de éxito

Al completar el programa, una persona independiente debe poder reconstruir una decisión y responder, sin inferencias:

1. Qué datos estaban disponibles exactamente en el momento de la señal.
2. Qué versión de código, datos, dependencias, configuración y modelo produjo el resultado.
3. Cómo se ajustaron precios por splits/dividendos y cómo se simularon órdenes, gaps y costos.
4. Qué universo y benchmark se usaron.
5. Qué periodos fueron train, validation y test final.
6. Cuántas hipótesis y parámetros fueron probados.
7. Cuál es la incertidumbre estadística del resultado.
8. Por qué una estrategia fue rechazada, quedó en shadow o avanzó a paper.
9. Qué límites de riesgo estaban vigentes antes de cada orden.
10. Cómo se reconcilia el estado interno con el broker.

## 3. Alcance

### Incluido

- Gobierno de ramas, CI/CD, entornos y despliegues.
- Contratos de datos, schemas, linaje, calidad e idempotencia.
- Datos point-in-time para precios, fundamentales, earnings, macro y universo.
- Corporate actions y separación raw/adjusted.
- Backtesting ejecutable con entradas, gaps, costos y calendarios realistas.
- Experiment registry y reproducibilidad completa.
- Validación cuantitativa nested walk-forward y test final bloqueado.
- Benchmarks y métricas de riesgo/retorno.
- Strategy Brain aislado por corrida y limitado a hipótesis auditables.
- Seguridad del executor, outbox, idempotencia, reconciliación y kill switches.
- Observabilidad, SLO, alertas, runbooks, rollback y disaster recovery.
- Documentación versionada, ADRs y matriz de trazabilidad.
- Protocolo posterior de optimización matemática por activo.

### Fuera de alcance hasta completar los gates

- Habilitar dinero real.
- Promover automáticamente estrategias.
- Ampliar el universo para mejorar métricas.
- Agregar más indicadores sin hipótesis registrada.
- Entrenar ML complejo o reinforcement learning.
- Optimizar parámetros por activo antes de tener datos y validación confiables.
- Presentar resultados legacy como evidencia vigente.

## 4. Principios de diseño

### 4.1 Correctitud temporal antes que sofisticación

Toda observación debe tener al menos:

```text
event_time     momento económico del hecho
available_at   primer instante en que el sistema podía conocerlo
ingested_at    instante de carga
```

Los backtests unen por `available_at <= signal_timestamp`, nunca solo por fecha de periodo.

### 4.2 Ejecución y análisis usan series distintas

```text
raw OHLC       ejecución, stops, take profit, gaps
adjusted close retornos, tendencia, benchmarks
corporate actions trazabilidad de splits y dividendos
```

### 4.3 Investigación y ejecución son planos separados

```text
research/backtest -> shadow -> paper -> live-canary -> live
```

Ninguna tabla o servicio de investigación debe habilitar ejecución por sí mismo.

### 4.4 Un experimento es una unidad inmutable

Cada experimento registra:

```text
experiment_id
parent_experiment_id
git_sha
image_digest
dataform_compilation_id
data_snapshot_id
universe_version
configuration_hash
dependency_lock_hash
model_name + prompt_version
random_seed
train/validation/test windows
hypothesis_count
results_checksum
```

### 4.5 La IA propone hipótesis, no autoriza parámetros

Los LLM pueden explicar, clasificar evidencia y proponer hipótesis estructuradas. No pueden autoasignar evidencia, contar repeticiones, aprobar su propia recomendación ni modificar una configuración ejecutable.

## 5. Arquitectura objetivo

```text
External sources
  |-- Market data primary
  |-- Market data reconciliation source
  |-- Corporate actions
  |-- SEC/IR filings and earnings
  |-- Macro sources
  |-- Alpaca Paper
          |
          v
Ingestion services (Cloud Run)
  - immutable ingestion_run_id
  - source metadata
  - quality status
  - retries bounded
          |
          v
BigQuery zones
  raw_immutable
  normalized_point_in_time
  research_features
  research_experiments
  shadow_signals
  paper_execution
  audit_and_observability
          |
          v
Dataform
  contracts -> canonical data -> features -> signals -> backtests
          |
    +-----+----------------+----------------+
    |                      |                |
    v                      v                v
Research engine       Dashboard         Shadow/Paper policy
    |                                       |
    v                                       v
Experiment registry                    Outbox executor
                                            |
                                            v
                                      Alpaca Paper
                                            |
                                            v
                                     Reconciliation
```

Los datasets físicos pueden consolidarse inicialmente si el costo lo exige, pero los límites lógicos y permisos deben mantenerse.

## 6. Work packages y orden obligatorio

| Orden | ID | Work package | Bloquea |
|---:|---|---|---|
| 0 | WP-00 | Congelamiento, inventario y baseline reproducible | Todos |
| 1 | WP-01 | Gobierno de ramas, CI y separación deploy | Todos los cambios seguros |
| 2 | WP-02 | Contratos de datos y experiment registry | WP-03 a WP-12 |
| 3 | WP-03 | Fundamentales/earnings point-in-time | Validez cuantitativa |
| 4 | WP-04 | Precios, corporate actions y granularidad canónica | Backtest confiable |
| 5 | WP-05 | Motor de backtest realista y capital | Validación |
| 6 | WP-06 | Aislamiento y corrección del Strategy Brain | Optimización |
| 7 | WP-07 | Framework cuantitativo, benchmarks y test final | Promoción |
| 8 | WP-08 | Executor fail-closed, outbox y reconciliación | Paper automático |
| 9 | WP-09 | Observabilidad, SLO, runbooks y DR | Operación sostenida |
| 10 | WP-10 | Seguridad, IAM, secretos y entornos | Producción segura |
| 11 | WP-11 | Documentación generada y auditoría continua | Auditabilidad |
| 12 | WP-12 | Optimización matemática por grupo/activo | Fórmulas finales |

No ejecutar WP-12 antes de aprobar WP-00 a WP-11.

## 7. Entregables del programa

- Contratos versionados de todas las tablas críticas.
- Dataset y fixtures golden para regresión.
- Backtest determinístico con checksum.
- Reporte de no-look-ahead.
- Reporte de corporate actions.
- Reporte de ejecución y slippage.
- Benchmark report.
- Walk-forward report.
- Multiple-testing report.
- Experiment registry y lineage.
- Executor state machine y reconciliation report.
- CI required checks y deploy con environment approval.
- Runbooks de incidentes, backfill y rollback.
- Scorecard 10/10 con evidencia enlazada.

## 8. Criterio para invalidar resultados anteriores

Todo resultado calculado antes de implementar WP-03, WP-04, WP-05 y WP-06 se etiqueta:

```text
LEGACY_PRE_AUDIT_GRADE
NOT_ELIGIBLE_FOR_PROMOTION
```

No se elimina. Se conserva para auditoría, pero no puede compararse como si tuviera la misma semántica que un resultado posterior.

## 9. Documentos normativos

- `00_current_state_and_target.md`: baseline de las once dimensiones, techos y work packages requeridos.
- `01_target_architecture.md`: arquitectura, límites y estados.
- `02_data_contracts_and_point_in_time.md`: contratos y migraciones de datos.
- `03_quant_validation_standard.md`: metodología cuantitativa.
- `04_execution_safety_standard.md`: seguridad de órdenes.
- `05_testing_ci_reproducibility.md`: pruebas y CI.
- `06_implementation_backlog.md`: tareas, archivos y aceptación.
- `07_codex_execution_prompts.md`: prompts secuenciales para Codex.
- `08_traceability_matrix.md`: requerimiento -> código -> prueba -> evidencia.
- `09_release_and_promotion_gates.md`: shadow, paper y live.
- `10_operability_runbooks.md`: operación e incidentes.
- `11_scorecard_10_of_10.md`: definición objetiva de 10/10.
- `12_per_asset_optimization_protocol.md`: optimización final por activo.

## 10. Política de cierre

Una tarea, work package o gate no se marca completado por una descripción, un deploy verde o una métrica atractiva. Debe existir evidencia fresca, reproducible y vinculada en la matriz de trazabilidad.

La plataforma puede alcanzar 10/10 en diseño, implementación y auditabilidad. La condición “lista para dinero real” requiere además evidencia operativa acumulada en shadow y paper; no puede concederse solo mediante código.
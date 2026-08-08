# 01 — Arquitectura objetivo

## 1. Objetivo arquitectónico

La arquitectura debe separar seis responsabilidades que hoy están parcialmente mezcladas:

1. adquisición de datos;
2. normalización point-in-time;
3. investigación y features;
4. generación de señales shadow;
5. ejecución paper;
6. auditoría y observabilidad.

El diseño objetivo prioriza correctitud temporal, aislamiento de experimentos, seguridad fail-closed y reproducibilidad.

## 2. Estados permitidos

```text
RESEARCH_ONLY
BACKTEST_ONLY
SHADOW_ONLY
PAPER_CANDIDATE
PAPER_CHAMPION
LIVE_CANARY
LIVE_APPROVED
DISABLED
```

### Reglas

- `RESEARCH_ONLY` y `BACKTEST_ONLY` nunca son consumidos por ejecutores.
- `SHADOW_ONLY` genera señales observables sin orden.
- `PAPER_CANDIDATE` se mide en paralelo, pero no recibe capital paper automático salvo gate explícito.
- `PAPER_CHAMPION` puede ser consumido por el executor Paper.
- `LIVE_CANARY` y `LIVE_APPROVED` no deben existir funcionalmente hasta una iniciativa posterior aprobada.
- Toda transición es manual, registrada y reversible.

## 3. Entornos

### Desarrollo

- proyecto/dataset aislado;
- datos sintéticos o subset anonimizado;
- Alpaca no requerido;
- cambios rápidos;
- sin schedulers productivos.

### Staging

- schemas y servicios equivalentes a producción;
- datos recientes limitados;
- broker fake o Alpaca Paper separado;
- pruebas de migración, reconciliación y rollback.

### Producción de investigación/paper

- datos completos;
- permisos mínimos;
- deploy solo desde commit aprobado;
- schedulers controlados;
- Alpaca Paper;
- observabilidad y retención.

La implementación puede comenzar con datasets separados dentro del mismo proyecto, pero el objetivo es separar proyectos o al menos service accounts y permisos por entorno.

## 4. Zonas de datos

### 4.1 `raw_immutable`

Propósito: conservar exactamente lo recibido de cada fuente.

Invariantes:

- append-only;
- payload original o hash verificable;
- `ingestion_run_id`;
- `source` y `source_version`;
- `received_at`;
- no corregir historia sobrescribiendo filas.

### 4.2 `normalized_point_in_time`

Propósito: datos limpios con semántica temporal explícita.

Columnas mínimas comunes:

```text
record_id
entity_id / ticker
event_time
available_at
ingested_at
valid_from
valid_to
source
source_record_id
revision
quality_status
```

### 4.3 `research_features`

Propósito: series canónicas, features, perfiles y contextos usados por investigación.

Reglas:

- toda fila conserva `feature_set_version`;
- toda feature indica inputs y ventana;
- no consume datos con `available_at > signal_timestamp`;
- no mezcla granularidades sin selección canónica.

### 4.4 `research_experiments`

Propósito: registrar hipótesis, corridas, candidatos, métricas y artefactos.

Tablas objetivo:

```text
experiment_runs
experiment_hypotheses
experiment_candidates
experiment_trade_ledger
experiment_equity_curves
experiment_metrics
experiment_statistical_tests
experiment_artifacts
experiment_decisions
```

### 4.5 `shadow_signals`

Propósito: señales generadas sobre datos actuales sin ejecución.

Cada señal contiene:

```text
signal_id
signal_timestamp
ticker
strategy_id
strategy_version
feature_set_version
config_hash
data_snapshot_id
experiment_or_policy_version
direction
entry_plan
risk_plan
explainability_payload
execution_eligible = false por defecto
```

### 4.6 `paper_execution`

Propósito: intenciones, órdenes, fills, posiciones y reconciliación.

Tablas objetivo:

```text
order_intents
broker_orders
broker_fills
position_snapshots
risk_decisions
reconciliation_runs
reconciliation_findings
kill_switch_state
```

### 4.7 `audit_and_observability`

Propósito: logs funcionales, calidad, lineage, SLO, incidentes y cambios.

## 5. Servicios objetivo

### Ingestion services

- `market-data-ingestor`
- `corporate-actions-ingestor`
- `fundamentals-ingestor`
- `earnings-ingestor`
- `macro-ingestor`

Cada servicio crea un `ingestion_run_id`, persiste estado y publica un resultado de calidad.

### Transformation and validation

- Dataform compila modelos por entorno.
- Un workflow específico ejecuta contratos y assertions.
- Un snapshot exitoso recibe `data_snapshot_id`.
- Un snapshot fallido nunca se marca elegible para señales.

### Research orchestrator

- crea `experiment_id` antes de generar candidatos;
- fija código, datos, configuración y ventanas;
- ejecuta backtest determinístico;
- produce artefactos inmutables;
- no modifica política shadow/paper.

### Signal service

- consume solo snapshots aprobados;
- produce señales shadow;
- no llama al broker.

### Policy service

- decide rol champion/challenger;
- requiere evidencia registrada y aprobación humana;
- produce una política versionada e inmutable.

### Execution service

- consume únicamente señales `execution_eligible = true` de una política aprobada;
- crea intención antes de enviar;
- aplica risk gate;
- llama a Alpaca Paper;
- reconcilia por `client_order_id`.

### Risk and reconciliation service

- controla posiciones y fills;
- valida quotes y reloj;
- aplica stops/time exits;
- bloquea entradas ante inconsistencias;
- mantiene kill switches.

## 6. Trust boundaries

```text
Internet sources -> untrusted
Raw payloads     -> untrusted but preserved
Normalized PIT   -> trusted after contracts
Research output  -> non-executable
Shadow policy    -> non-executable
Paper policy     -> executable only in Alpaca Paper
Broker state     -> source of truth for orders/fills
Internal state   -> must reconcile against broker
LLM output       -> untrusted hypothesis/explanation
```

## 7. Lineage obligatorio

Toda señal debe poder seguirse así:

```text
broker_order
  -> order_intent
  -> approved_policy_version
  -> shadow_signal
  -> feature rows
  -> normalized records
  -> raw source payloads
  -> ingestion_run
```

Toda métrica de backtest debe poder seguirse así:

```text
metric
  -> equity curve
  -> trade ledger
  -> candidate/config
  -> experiment run
  -> data snapshot
  -> code/dependency/image version
```

## 8. Versionado

### Versiones separadas

- `data_contract_version`
- `feature_set_version`
- `strategy_version`
- `execution_model_version`
- `cost_model_version`
- `universe_version`
- `policy_version`
- `prompt_version`

No usar un único string para representar todas las dimensiones.

## 9. Disponibilidad y consistencia

La plataforma favorece consistencia por sobre disponibilidad para decisiones ejecutables:

- si falta una fuente crítica, señal degradada o no elegible;
- si no se puede reconciliar el broker, no hay nuevas entradas;
- si una migración parcial deja schemas incompatibles, rollback;
- si el snapshot no tiene contratos verdes, no se publica.

## 10. Deuda técnica a retirar

- DDL disperso entre Terraform, Python y Dataform.
- proyecto/dataset hardcodeado en SQL.
- deploy desde `master` y `main`.
- tablas de investigación y ejecución en el mismo plano lógico.
- ramas no protegidas.
- dependencias sin lock reproducible.
- candidatos identificados sin `run_id` completo.
- estados de aprobación derivados de texto de IA.

## 11. Estrategia de migración

1. Crear contratos y tablas nuevas en paralelo.
2. Dual-write donde sea necesario.
3. Backfill con `data_version = AUDIT_GRADE_V1`.
4. Ejecutar reconciliación entre legacy y nuevo.
5. Cambiar consumidores de research.
6. Mantener ejecución en shadow.
7. Retirar legacy solo después de evidencia y rollback probado.

Ningún cambio destructivo se realiza en la primera fase.
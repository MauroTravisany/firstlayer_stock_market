# 05 — Pruebas, CI y reproducibilidad

## 1. Objetivo

Un workflow verde debe demostrar comportamiento relevante, no solo que Python compila y Cloud Run acepta un deploy. La estrategia de pruebas se organiza por riesgos observables.

## 2. Gobierno de ramas

Estado objetivo:

- rama canónica: `main`;
- `master` se reconcilia y archiva;
- deploy solo desde `main`;
- `main` protegida;
- PR obligatoria;
- al menos una aprobación para cambios críticos;
- required checks;
- force push y deletion bloqueados;
- CODEOWNERS para datos, backtest, executor e infraestructura;
- environment approval para deploy.

El workflow de deploy no debe activarse desde `master` ni desde ramas de feature.

## 3. Workflows separados

### `ci.yml`

Se ejecuta en PR y push a `main`:

1. checkout;
2. setup Python/Node;
3. dependency lock verification;
4. secret scanning;
5. lint/format;
6. type checks;
7. unit tests;
8. property tests;
9. contract tests;
10. Dataform compile;
11. BigQuery dry-run en entorno de test;
12. golden backtest regression;
13. dashboard build;
14. Terraform fmt/validate/plan;
15. artifact/report upload.

### `deploy.yml`

Se ejecuta solo cuando CI exitoso en `main`:

- environment approval;
- immutable image digest;
- migraciones aditivas;
- deploy staging;
- smoke tests;
- aprobación/promoción a prod research/paper;
- verificación post-deploy;
- rollback automático si smoke falla.

### `scheduled-validation.yml`

- source reconciliation;
- data quality;
- deterministic replay sample;
- drift report;
- broker reconciliation;
- dashboard freshness;
- no despliega código.

## 4. Estructura de pruebas objetivo

```text
tests/
  unit/
    data/
    quant/
    execution/
    ai/
  property/
  contracts/
  integration/
    bigquery/
    dataform/
    broker_fake/
    alpaca_paper/
  golden/
    fixtures/
    expected/
  e2e/
  helpers/
```

## 5. Fixtures golden

Crear datasets pequeños, legibles y calculables manualmente.

### Precios

- tendencia simple;
- split 2:1;
- dividendo;
- vela diaria + intradía duplicada;
- sesión incompleta;
- DST;
- feriado;
- gap bajo stop;
- stop y TP en misma vela;
- cripto 24/7.

### Fundamentales

- periodo terminado 31/03, filing publicado 02/05;
- cuatro trimestres para YoY;
- restatement;
- filing tardío;
- dato sin `available_at` verificable;
- ratio derivado desde estado y precio.

### Strategy Brain

- dos corridas el mismo día;
- candidato overall no elegible y candidato elegible;
- primer trade perdedor;
- varias hipótesis y ajuste de confianza;
- nested folds con test bloqueado.

### Executor

- cuenta/posición/quote OK;
- cada dependencia fallando;
- order accepted y persistencia falla;
- duplicate retry;
- partial fill;
- límite alcanzado durante loop;
- kill switch.

## 6. Unit tests

Cubren funciones puras y reglas locales:

- parsing y validación;
- IDs determinísticos;
- corporate action adjustments;
- cálculos de retornos y métricas;
- fill model;
- risk gate;
- state transitions;
- JSON schemas;
- config bounds.

Los expected values se calculan desde especificaciones independientes, no copiando la implementación.

## 7. Property tests

Invariantes recomendados:

- IDs estables para mismo input y distintos para corridas distintas;
- ninguna observación futura entra a una señal;
- adjusted return es continuo tras split;
- equity = capital inicial + PnL acumulado;
- running peak >= capital inicial;
- drawdown >= 0;
- una cartera one-slot no solapa operaciones;
- retries no duplican órdenes;
- límites nunca se exceden;
- mismo snapshot/config produce mismo checksum.

## 8. Contract tests de datos

Cada tabla crítica tiene pruebas de:

- schema;
- tipos;
- nullability;
- uniqueness;
- accepted values;
- freshness;
- timezone;
- row-level temporal invariant;
- referential integrity;
- lineage.

Los contratos se versionan en archivos legibles por máquina, por ejemplo `contracts/*.yaml`.

## 9. Pruebas Dataform/BigQuery

### Compilación

- compilar todos los modelos;
- prohibir warnings críticos;
- detectar referencias hardcodeadas fuera de entorno.

### Dry-run

- estimar bytes;
- detectar errores de schema;
- ejecutar en dataset efímero.

### Golden SQL

Cargar fixtures en BigQuery de test y comparar tablas resultantes completas o checksums contra expected.

Casos obligatorios:

- no-look-ahead;
- YoY deduplicado;
- selección de vela canónica;
- gap fills;
- time exits por sesión;
- capital y drawdown;
- aislamiento por experiment/run ID.

## 10. Pruebas cuantitativas de regresión

No fijar únicamente PnL exacto de producción. Mantener dos niveles:

### Fixture determinístico

Resultados exactos:

```text
trade ledger
equity curve
metrics
checksum
```

### Snapshot de producción controlado

Comparar:

- cambios de número de filas/trades;
- diferencias de métricas;
- cambios de clasificación;
- performance/costo de consulta;
- data quality.

Cambios esperados requieren un archivo de aprobación y explicación.

## 11. Broker fake y contract tests

Implementar un fake server/stateful adapter con los mismos contratos usados por el cliente Alpaca.

Debe simular:

- account;
- positions;
- clock;
- create/get/cancel order;
- accepted/rejected/partial/fill;
- timeouts antes/después de aceptación;
- duplicate client order IDs;
- stale quotes.

La mayor parte de la seguridad se prueba contra este fake. Las pruebas Alpaca Paper reales son pocas, controladas y separadas.

## 12. Cobertura

No usar porcentaje global como único gate.

Gates mínimos:

- 100% de los invariantes críticos con prueba explícita;
- ramas de error del executor cubiertas;
- migraciones con prueba de forward y rollback;
- cada bug material recibe regression test;
- cobertura de líneas orientativa, no sustituto de comportamiento.

## 13. Reproducibilidad

### Dependencias

- usar archivos de entrada y lock por servicio;
- pin de versiones y hashes;
- actualizar mediante PR automatizada;
- registrar lock hash en experimentos.

### Contenedores

- construir imagen una vez;
- promover por digest;
- no reconstruir entre staging/prod;
- SBOM y vulnerability scan.

### Datos

- cada corrida usa `data_snapshot_id`;
- raw mutable externo no se consulta durante replay;
- artefactos guardan checksum;
- snapshot retenido o reconstruible.

### Configuración

- canonical JSON ordenado;
- `configuration_hash`;
- variables de entorno efectivas sin secretos;
- prompt/model version.

### Randomness

- seeds explícitas;
- algoritmos determinísticos cuando sea posible;
- diferencias no determinísticas documentadas.

## 14. Comando de reproducción

Todo experimento debe producir un comando equivalente a:

```bash
python -m research.replay \
  --experiment-id EXP_ID \
  --data-snapshot SNAPSHOT_ID \
  --verify-checksum
```

Resultado esperado:

```text
REPRODUCED
trade_ledger_checksum=...
metrics_checksum=...
```

## 15. Seguridad del CI

- OIDC/Workload Identity Federation;
- permisos mínimos por job;
- no usar service-account JSON de larga vida;
- secrets solo en deploy/integration autorizada;
- fork PRs sin acceso a secrets;
- dependency and secret scanning;
- artifacts sin datos sensibles;
- logs redacted.

## 16. Terraform e infraestructura

CI debe validar:

- `terraform fmt`;
- `terraform validate`;
- plan sin cambios destructivos no aprobados;
- policy checks para public access, deletion protection, IAM amplio y regiones;
- drift report periódico.

## 17. Smoke tests post-deploy

- health endpoints;
- auth OIDC;
- dry-run de ingesta;
- Dataform compilation/result freshness;
- signal generation shadow;
- executor dry-run sin orden;
- broker reconciliation read-only;
- dashboard sources.

Un fallo revierte al digest anterior y pausa schedulers afectados.

## 18. Criterios de aceptación

- ninguna rama despliega sin CI y aprobación;
- `master` no despliega;
- tests críticos reproducen defectos conocidos;
- golden backtest es determinístico;
- Dataform se prueba en dataset aislado;
- broker failures son fail-closed;
- dependencias e imágenes son identificables;
- cada experimento se reproduce por ID;
- CI produce evidencia enlazable desde la matriz de trazabilidad.
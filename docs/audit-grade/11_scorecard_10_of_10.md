# 11 — Scorecard objetivo 10/10

## 1. Uso

Este scorecard no es una autoevaluación subjetiva. Cada dimensión se califica con evidencia. Para obtener 10/10 no pueden existir hallazgos críticos/altos abiertos en la dimensión y todos los criterios obligatorios deben estar en `PASS` en la matriz de trazabilidad.

## 2. Documentación ejecutiva — objetivo 10/10

### Criterios

- arquitectura y flujos actuales, no históricos sin marcar;
- front matter con commit, snapshot, status y revisión;
- ADRs para decisiones materiales;
- glosario y catálogo generado desde contratos;
- resultados con metodología y limitaciones;
- runbooks y owners;
- current/superseded explícito;
- CI detecta drift docs/código;
- lectura ejecutiva y técnica separadas;
- no hay afirmaciones sin evidencia enlazada.

### Evidencia

- documentation build;
- drift check;
- ADR index;
- traceability links.

## 3. Arquitectura conceptual — objetivo 10/10

### Criterios

- límites claros entre raw, PIT, research, shadow y execution;
- entornos separados;
- state machines explícitas;
- data/source trust boundaries;
- versionado independiente de datos/features/estrategia/ejecución/costos;
- experiment registry;
- policy service separado del tuner;
- infraestructura como código;
- rollback y DR;
- no hay camino research -> order sin gate.

## 4. Trazabilidad y auditoría — objetivo 10/10

### Criterios

Toda señal/orden y toda métrica se reconstruye hasta:

```text
raw source
normalized record
data snapshot
feature set
config hash
strategy/policy version
code SHA/image digest
experiment/signal/order IDs
approval/evidence checksum
```

Además:

- logs correlacionados;
- artifacts inmutables;
- auditor independiente puede reproducir;
- resultados legacy e invalidados preservados;
- toda promoción tiene decisión firmada.

## 5. Ingeniería de datos — objetivo 10/10

### Criterios

- contratos machine-readable;
- `available_at` real;
- vintages/revisions;
- corporate actions;
- raw append-only;
- serie canónica sin mezcla de granularidades;
- segunda fuente y reconciliación;
- calendarios/timezones;
- idempotencia;
- freshness/completeness/uniqueness/domain assertions;
- lineage;
- backfills versionados;
- costos y performance monitoreados;
- cero look-ahead material.

## 6. Validez cuantitativa — objetivo 10/10

### Criterios

- protocolo pre-registrado;
- ejecución/fills/costos realistas;
- fixed-notional y self-financing separados;
- nested walk-forward;
- purging/embargo;
- final locked test;
- benchmarks;
- incertidumbre e intervalos;
- multiple-testing adjustment;
- estabilidad por fold/año/activo/régimen;
- sensibilidad de parámetros/costos;
- universe PIT;
- no concentration accidental;
- métricas independientes verificadas;
- resultado reproducible por checksum.

Un resultado puede ser metodológicamente 10/10 y concluir que no existe alpha. La calidad de la metodología no depende de que el retorno sea positivo.

## 7. Seguridad actual en shadow — objetivo 10/10

### Criterios

- `SHADOW_ONLY` enforced por código y CI;
- research no puede crear órdenes;
- no auto-promotion;
- LLM no aprueba;
- kill switch de señales;
- datos degradados bloquean elegibilidad;
- least privilege;
- secrets protegidos;
- incident/runbook;
- alertas ante policy drift.

## 8. Seguridad del executor — objetivo 10/10

### Criterios

- Paper-only enforced;
- fail-closed;
- outbox/persist-before-send;
- idempotency/retry/reconciliation;
- risk gate por orden;
- quote freshness/spread;
- límites de exposición/pérdida;
- state machine;
- kill switches;
- fake broker y Paper integration tests;
- cero duplicados/untracked positions;
- broker es fuente de verdad para fills;
- auditoría completa.

## 9. Pruebas y reproducibilidad — objetivo 10/10

### Criterios

- test pyramid orientada a riesgos;
- fixtures golden;
- property tests de invariantes;
- contract tests;
- Dataform/BigQuery integration tests;
- fake broker;
- regression tests de todos los defects materiales;
- CI required;
- dependencies locked;
- image digest/SBOM;
- data snapshots;
- config/seed/hash;
- replay command y checksums;
- staging/smoke/rollback tests;
- evidencia fresca.

## 10. Gobierno de ramas y despliegues — objetivo 10/10

### Criterios

- `main` única rama canónica;
- branch protection;
- PR/review/required checks;
- CODEOWNERS;
- build once/promote digest;
- deploy solo tras CI;
- environment approvals;
- staging antes de prod;
- Terraform/policy checks;
- WIF;
- rollback;
- release manifest;
- `master` no despliega.

## 11. Plataforma personal de investigación — objetivo 10/10

### Criterios

- hypotheses y experiments registrados;
- datos/ledger/métricas reproducibles;
- benchmarks y reports automáticos;
- aislamiento de corridas;
- capacidad de comparar versiones sin sobrescribir;
- dashboard de evidencia;
- costo y duración visibles;
- no se confunde exploración con validación;
- optimización jerárquica controlada;
- investigación nunca modifica policy ejecutable.

## 12. Sistema listo para dinero real — objetivo 10/10

Esta dimensión no puede alcanzar 10/10 mediante código únicamente.

### Evidencia de plataforma

- Gates G0–G7 aprobados;
- seguridad, IAM, DR, observabilidad y reconciliación;
- threat model y controles humanos;
- cumplimiento/broker review;
- live-canary architecture.

### Evidencia de estrategia

- Gates G3–G6 aprobados;
- paper prolongado y suficiente para su frecuencia;
- fills y slippage calibrados;
- distintos regímenes;
- drawdown/risk budget respetado;
- cero incidentes críticos;
- aprobación independiente.

### Evidencia live

- G8 canary controlado;
- resultado/reconciliación real;
- nueva aprobación G9.

Sin esa evidencia el score máximo de esta dimensión debe permanecer limitado, aunque el código sea excelente.

## 13. Regla de puntuación

Sugerencia de cálculo auditable:

```text
10.0 = todos los criterios obligatorios PASS, sin high/critical abiertos
9.0  = todos los críticos PASS, solo gaps menores con mitigación
8.0  = diseño sólido, evidencia parcial en una capa material
7.0  = funciona, pero existen riesgos materiales no verificados
5.0  = implementación parcial o metodología vulnerable
3.0  = resultados no confiables o seguridad incompleta
1.0  = control mínimo
0.0  = inexistente
```

No promediar un fallo crítico con varios checks fáciles. Los critical gates actúan como techo.

## 14. Techos por hallazgo

| Hallazgo abierto | Techo de dimensión |
|---|---:|
| Look-ahead material | Validez cuantitativa <= 3 |
| Corridas contaminadas | Trazabilidad/validez <= 4 |
| Sin test final independiente | Validez <= 6 |
| Executor falla abierto | Executor <= 5 |
| Sin reconciliación | Executor/live <= 5 |
| Dos ramas despliegan | Gobierno <= 5 |
| Sin tests cuantitativos | Pruebas <= 4 |
| Sin evidencia paper/live | Listo para real <= 4 |

## 15. Review final

El score se recalcula mediante una auditoría read-only independiente. El reviewer debe inspeccionar código, schemas, pruebas, CI, manifests y artefactos; no aceptar la documentación como prueba de sí misma.
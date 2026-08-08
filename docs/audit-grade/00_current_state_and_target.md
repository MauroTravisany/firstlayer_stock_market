# 00 — Estado inicial y objetivo por dimensión

## 1. Baseline de auditoría

Este baseline fue establecido sobre el estado previo al programa audit-grade. Es una evaluación de madurez, no una medición automática.

| Dimensión | Baseline | Principal techo actual |
|---|---:|---|
| Documentación ejecutiva | 8,4/10 | Documentos sin versionado/current-superseded ni evidencia enlazada completa |
| Arquitectura conceptual | 8,0/10 | Research, datos, políticas y ejecución aún comparten límites e infraestructura |
| Trazabilidad y auditoría | 7,5/10 | Corridas/candidatos no completamente aislados; falta experiment registry inmutable |
| Ingeniería de datos | 5,2/10 | Look-ahead financiero, corporate actions/granularidad y segunda fuente incompletos |
| Validez cuantitativa | 3,5/10 | Validation adaptativa, sin final locked test, benchmarks ni múltiples pruebas |
| Seguridad actual en shadow | 8,5/10 | Buen bloqueo actual, pero CI/policy enforcement/kill switches incompletos |
| Seguridad del executor | 5,0/10 | Falla abierta, límites por loop, notional fallback y reconciliación incompleta |
| Pruebas y reproducibilidad | 2,8/10 | CI orientado a compile/deploy, sin golden/contract/quant/broker suites |
| Gobierno de ramas/despliegues | 4,0/10 | `master` default, `main` y `master` despliegan, checks/protección insuficientes |
| Plataforma personal de investigación | 6,6/10 | Buena amplitud, pero experimentos/resultados no totalmente reproducibles |
| Sistema listo para dinero real | 2,2/10 | Falta evidencia metodológica, Paper, seguridad operativa y live-canary |

## 2. Objetivo

| Dimensión | Work packages que desbloquean 10/10 de implementación |
|---|---|
| Documentación ejecutiva | WP-00, WP-02, WP-09, WP-11 |
| Arquitectura conceptual | WP-01, WP-02, WP-08, WP-10 |
| Trazabilidad y auditoría | WP-00, WP-02, WP-05, WP-06, WP-11 |
| Ingeniería de datos | WP-02, WP-03, WP-04, WP-09 |
| Validez cuantitativa | WP-03, WP-04, WP-05, WP-06, WP-07 |
| Seguridad actual en shadow | WP-01, WP-08, WP-09, WP-10 |
| Seguridad del executor | WP-08, WP-09, WP-10 |
| Pruebas y reproducibilidad | WP-01, WP-02, WP-03–WP-08, WP-10 |
| Gobierno de ramas/despliegues | WP-01, WP-10 |
| Plataforma personal de investigación | WP-02, WP-05, WP-06, WP-07, WP-11, WP-12 |
| Sistema listo para dinero real | Gates G0–G9; no se obtiene solo mediante implementación |

## 3. Techos obligatorios mientras existan blockers

| Blocker | Techo aplicable |
|---|---:|
| `available_at` no verificable/look-ahead | Ingeniería <= 6; validez <= 3 |
| Corporate actions/granularidad ambigua | Ingeniería <= 7; validez <= 5 |
| Corridas contaminables por IDs/joins | Trazabilidad <= 5; validez <= 4 |
| Validation usada repetidamente sin test final | Validez <= 6 |
| Sin benchmarks/uncertainty/multiple testing | Validez <= 7 |
| Executor falla abierto o sin outbox | Executor <= 5; real <= 3 |
| Sin reconciliación/kill switch probado | Executor <= 7; real <= 4 |
| Dos ramas despliegan | Gobierno <= 5 |
| Sin golden/contract/integration tests | Pruebas <= 5 |
| Sin shadow/paper evidence | Real <= 4 |
| Sin live-canary evidence | Real < 10 |

## 4. Estados esperados por fase

### Después de WP-00 a WP-02

- baseline, contracts, identidad y CI encaminados;
- no se recalifica validez todavía;
- resultados legacy siguen no elegibles.

### Después de WP-03 y WP-04

- datos PIT/canónicos disponibles;
- se invalida/recalcula historia afectada;
- ingeniería de datos puede ser reauditada.

### Después de WP-05 a WP-07

- backtest y Strategy Brain reproducibles;
- aparece evidencia OOS y benchmarks;
- validez cuantitativa puede acercarse a 10/10 aunque la conclusión sea “sin alpha”.

### Después de WP-08 a WP-10

- executor Paper seguro, observabilidad e infraestructura gobernada;
- todavía no se habilita Paper Champion sin Gate G6.

### Después de WP-11

- documentación y trazabilidad pueden ser auditadas como sistema completo.

### Después de WP-12

- fórmulas grupales/por activo se optimizan con evidencia ya confiable;
- no es requisito que cada activo tenga fórmula diferente.

### Después de shadow/paper/live gates

- la dimensión “lista para dinero real” puede aumentar solo con evidencia operativa acumulada y aprobaciones, no por código nuevo.

## 5. Criterio de cierre

La auditoría final #48 recalcula todas las dimensiones. No se heredan los puntajes objetivo y no se redondea a 10/10 si una fila crítica de la matriz de trazabilidad no está en PASS.
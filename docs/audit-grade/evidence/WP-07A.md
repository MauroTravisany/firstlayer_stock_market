# WP-07A — Evidencia del núcleo probabilístico de valoración

## Identidad

```text
issue: #65
pull_request: #68
branch: chatgpt/wp-07a-probabilistic-valuation
base_sha: a4115dd7efd1f2721e3b36c3e3a6ad06a20bf36d
status: CODE_HARDENED_REMOTE_CI_REQUIRED
live_materialization: BLOCKED_BY_WP03_WP04
production_change_allowed: false
```

## Alcance implementado

- `PriceObservation` PIT con source hash, timestamps, snapshot y moneda;
- contratos tipados y lineage verificable;
- política versionada y hasheada;
- relative valuation por peers con robust scaling y leave-one-out;
- FCFF por escenarios;
- residual income;
- reverse DCF;
- calidad separada;
- value-trap score separado y calibración obligatoria para `ECONOMICA`;
- ensemble probabilístico;
- evidencia OOS ligada al model spec;
- Brier/log loss/ECE, interval coverage y effective sample size;
- conformal interval fail-closed;
- reason codes y hashes deterministas;
- routing fail-closed por tipo de entidad.

## Revisión independiente de hardening

La primera versión del PR pasó CI, pero la revisión de fórmulas encontró gaps
que los tests iniciales no cubrían. La versión endurecida corrige:

| Hallazgo | Corrección |
|---|---|
| Residuals relativos in-sample podían sobreestimar confianza | incertidumbre, RMSE y R² leave-one-out |
| Peers duplicados o sujeto dentro de sus peers | rechazo fail-closed |
| Muestra de peers insuficiente para el número de parámetros | floor por parámetro y por fold LOO |
| Peer/config hashes no ligados a inputs reales | recomputación y comparación exacta |
| Modelo podía declarar su propio peso | pesos pertenecen solo a policy |
| Hash de calibración arbitrario | evidence registry ligado a `model_spec_hash` y split OOS común |
| Dos copias del mismo modelo podían inflar el voto | nombres, specs y familias únicos |
| Low value-trap heuristic podía parecer probabilidad calibrada | estado desconocido hasta evidencia OOS; calibración requerida para `ECONOMICA` |
| Calidad sin lineage | quality assessment comparte snapshot/cutoff/currency y config hash |
| Precio sin lineage PIT | `PriceObservation` compatible con modelos y quality |
| Escenarios con probabilidad inconsistente o nombre duplicado | probabilidades suman uno y nombres únicos |
| Payout aplicado a pérdidas creaba dividendos negativos | pérdidas pagan dividendo cero |
| Resultado insuficiente fabricaba fair value igual al precio | distribución ausente usa quantiles/returns/probabilities nulos |
| `result_hash` era declarativo | constructor verifica hash contra payload completo |
| Weighted calibration podía ocultar muestra efectiva mínima | effective sample size obligatorio |
| Conformal interval podía cruzar cero | rechazo fail-closed |

## Verificación focalizada local

```text
python -m compileall -q packages tests
exit: 0

python -m unittest discover -s tests -p 'test_*.py'
valuation tests: 55
exit: 0
result: OK
```

Cobertura material:

- calidad alta no convierte caro en económico;
- value trap alto puede forzar abstención sin cambiar fair value;
- low risk no habilita `ECONOMICA` sin calibración OOS ligada;
- modelos, calidad o precio con lineage incompatible fallan cerrados;
- quantiles positivos y monotónicos en 100 ensembles aleatorios;
- DCF y residual income contra cálculos manuales;
- reverse DCF reproduce supuestos conocidos y no fuerza bounds;
- peer universe/config hash exactos;
- calibración pequeña o con effective sample bajo queda `INSUFFICIENT`;
- rutas de bancos/ETF/cripto rechazan modelos incompatibles;
- ausencia de red/cloud/broker/LLM/BigQuery;
- resultado y hash independientes del orden de modelos.

## Bloqueos deliberados

- no hay tablas Dataform WP-07A todavía;
- no se han usado datos BigQuery live;
- no existe calibración OOS real;
- no existe peer universe PIT live;
- no se modifica el clasificador del PR #64;
- no se conecta con Strategy Brain;
- no hay promoción ni órdenes.

## Próximo gate

Después de fusionar y validar WP-03/WP-04:

```text
valuation_features_pit
→ relative/intrinsic scenarios
→ OOS calibration evidence registry
→ valuation_ensemble_pit
→ shadow comparison
```

# WP-07A — Evidencia del núcleo probabilístico de valoración

## Identidad

```text
issue: #65
branch: chatgpt/wp-07a-probabilistic-valuation
base_sha: a4115dd7efd1f2721e3b36c3e3a6ad06a20bf36d
status: CODE_IMPLEMENTED_LOCAL_VERIFICATION
live_materialization: BLOCKED_BY_WP03_WP04
production_change_allowed: false
```

## Alcance implementado

- contratos tipados y lineage;
- política versionada;
- relative valuation robusta por peers;
- FCFF por escenarios;
- residual income;
- reverse DCF;
- calidad separada;
- value-trap probability;
- ensemble probabilístico;
- calibración de probabilidades e intervalos;
- conformal interval expansion;
- reason codes y hashes deterministas;
- routing fail-closed por tipo de entidad.

## Verificación local

```text
python -m compileall -q packages tests
exit: 0

python -m unittest discover -s tests -p 'test_*.py'
tests: 43
exit: 0
result: OK
```

## Defectos cubiertos

| Riesgo | Control |
|---|---|
| Calidad convierte caro en barato | fair value no depende de `quality_score`; regression test |
| Precio justo como número exacto | quantiles p10/p25/p50/p75/p90 |
| Modelos con snapshots distintos | ensemble devuelve `DATOS_INSUFICIENTES` |
| Value trap oculto | probabilidad y abstención separadas |
| Regresión relativa inestable | robust scaling + ridge + empirical residuals |
| DCF con terminal inválido | fail-closed |
| Reverse DCF fuerza respuesta | `feasible=false` fuera de bounds |
| Poca evidencia aparenta calibración | `INSUFFICIENT` bajo min samples |
| Reglas por ticker | scan de package |
| Efectos laterales | scan sin red/cloud/broker/LLM/BigQuery |
| Fair values no monotónicos | validación y 100 ensembles aleatorios |
| Resultado no reproducible | hash determinista y test de reordenamiento |

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
→ valuation_ensemble_pit
→ calibration under WP-07
→ shadow comparison
```

# Auditoria M4 - Resultados y retroalimentacion del cerebro

Fecha: 2026-08-04  
Alcance: generaciones 1 y 2 del Strategy Brain; validacion 2025-01-01 a 2026-08-03.

## Veredicto ejecutivo

La retroalimentacion cuantitativa esta funcionando: la generacion 2 fue creada desde tres candidatos padre de la generacion 1 y no desde el baseline fijo. Sin embargo, la retroalimentacion de IA aun es interpretativa: se guarda, explica riesgos y bloquea produccion, pero no se parsea automaticamente para cambiar un peso numerico.

Ninguna estrategia es apta para produccion. Todos los candidatos permanecen en `BACKTEST_ONLY` y las dos generaciones tienen `production_change_allowed = false`.

## Evidencia de ejecucion

| Generacion | Corrida | Candidatos | Padres | Auditoria IA | Estado |
|---|---|---:|---:|---|---|
| G1 | `brain-20260804164359-7d0081` | 20 | 0 | registrada | sin candidato elegible |
| G2 | `brain-20260804174405-bcc320` | 18 | 3 | registrada | sin candidato elegible |

G2 tiene trazabilidad con `parent_run_id` hacia G1 y cada candidato conserva `parent_candidate_id`.

## Resultados netos: mejor candidato monetario por version

No se suman las versiones: V1-V4 son estrategias alternativas sobre el mismo universo.

| Version | Mejor G1 neto CLP | Mejor G2 neto CLP | Cambio CLP |
|---|---:|---:|---:|
| V1 | -3.408.472 | -2.785.806 | +622.666 |
| V2 | -3.420.441 | -2.749.409 | +671.032 |
| V3 | -15.343 | -13.149 | +2.194 |
| V4 | -471.454 | -404.102 | +67.352 |

La mejora en dinero no basta para aprobar una estrategia. El mejor profit factor sigue bajo 1.00 en todas las versiones (V3 queda cerca de 0.997), por lo que despues de spread y slippage el sistema sigue perdiendo.

## Calidad y diversidad de resultados

- Todos los trades cerrados de validacion presentan campos de miedo, earnings, regimen monetario, riesgo politico y contexto cripto.
- Esta cobertura indica que el pipeline propaga contexto. No demuestra que cada serie sea una fuente historica externa completa: algunos campos pueden ser proxies o valores de respaldo.
- G2 aumento la diversidad de PnL: V1 y V2 pasaron de 8/6 resultados monetarios distintos entre 20 candidatos a 15 resultados distintos entre 18 candidatos. La exploracion local si tuvo efecto.
- V3 y V4 mantienen menor diversidad porque sus senales tienen menos operaciones y los cambios contextuales no siempre alteran la entrada o salida.

## Retroalimentacion: que funciona y que falta

### Funciona

1. Se registra auditoria IA en espanol para cada corrida.
2. El motor selecciona padres desde resultados de validacion ya auditados.
3. La seleccion evita PnL bruto: considera profit factor, retorno neto, cola de perdidas, win rate y PnL neto.
4. Los guardrails bloquean cualquier cambio a produccion.

### Falta para cerrar el ciclo de IA

1. La IA todavia no transforma sus sugerencias textuales en una propuesta estructurada de cambios con limites y evidencia.
2. El motor usa un ranking global de V1-V4. Una futura mejora debe entrenar familias de pesos separadas por estrategia o perfil de activo.
3. El ranking debe penalizar mas explicitamente las mejoras que provienen solo de bajar notional. Menor perdida en CLP no necesariamente implica mejor alpha.
4. El historial contiene dos filas de auditoria para G1: la primera se insertó antes de un fallo de streaming buffer. La logica deduplica por `run_id`, por lo que no altero G2, pero debe mostrarse como evento tecnico duplicado.

## Recomendacion operativa

Mantener el scheduler semanal y acumular al menos 4 a 8 generaciones antes de ampliar el espacio de busqueda. La siguiente mejora debe convertir la salida IA a JSON estructurado de hipotesis, pero las propuestas deben seguir pasando por backtesting y guardrails cuantitativos antes de crear cualquier candidato nuevo.

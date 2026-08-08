# AGENTS.md — Reglas obligatorias para Codex

Este archivo gobierna cualquier cambio realizado por Codex en este repositorio. Su objetivo es transformar el proyecto en una plataforma cuantitativa auditable, reproducible y segura. Las instrucciones de `docs/audit-grade/` forman parte del contrato del repositorio.

## 1. Objetivo del programa

El objetivo no es producir el backtest con mayor rentabilidad histórica. El objetivo es construir un sistema que pueda demostrar, con evidencia independiente, qué datos conocía en cada instante, qué versión de código y configuración tomó cada decisión, cómo simuló la ejecución y por qué un resultado fue aceptado o rechazado.

La optimización de fórmulas por activo es la última etapa. No se debe optimizar ningún parámetro hasta completar los gates de datos point-in-time, simulación, reproducibilidad, validación estadística y seguridad operativa.

## 2. Estado de seguridad obligatorio

Hasta que todos los gates de `docs/audit-grade/09_release_and_promotion_gates.md` estén aprobados:

- `trading_champion_challenger_policy.execution_mode` debe permanecer en `SHADOW_ONLY`.
- `production_change_allowed` debe permanecer en `FALSE` para experimentos y candidatos.
- Ningún componente puede habilitar dinero real.
- Ningún cambio puede promover automáticamente un candidato a paper o real.
- Los ejecutores deben operar únicamente contra Alpaca Paper y fallar cerrados.
- No se debe desplegar desde una rama de trabajo.

Cambiar cualquiera de estas condiciones requiere una tarea separada, aprobación humana explícita y evidencia de todos los gates.

## 3. Forma de trabajo obligatoria

Cada work package se implementa en una PR separada y en el orden definido en `docs/audit-grade/06_implementation_backlog.md`.

Antes de modificar código:

1. Leer este archivo y la documentación del work package.
2. Identificar productores, consumidores, tablas, APIs y migraciones afectadas.
3. Definir invariantes y casos de fallo.
4. Crear una prueba que demuestre el defecto o el comportamiento faltante cuando sea posible.
5. Mantener compatibilidad o documentar una migración y rollback explícitos.

Después de modificar código:

1. Ejecutar pruebas focalizadas.
2. Ejecutar la suite amplia aplicable.
3. Compilar Dataform y hacer dry-run de consultas afectadas.
4. Revisar el diff para detectar secretos, cambios no relacionados y degradaciones de seguridad.
5. Actualizar documentación, contratos y matriz de trazabilidad.
6. Adjuntar en la PR comandos, resultados, limitaciones y evidencia.

No se permite una PR de “refactor general” que mezcle varios work packages críticos.

## 4. Invariantes cuantitativos no negociables

Toda implementación debe preservar y probar lo siguiente:

- **Point-in-time:** una señal solo puede usar información cuyo `available_at` sea menor o igual al `signal_timestamp`.
- **Sin look-ahead:** no se puede usar la fecha de cierre de un periodo contable como fecha de publicación.
- **Corporate actions:** ejecución usa precios raw; retornos y benchmarks usan series ajustadas identificables.
- **Granularidad canónica:** una vela diaria no puede sumar simultáneamente una vela 1d y sus velas intradía.
- **Entrada ejecutable:** una señal diaria entra como mínimo en la siguiente apertura observable, con costos.
- **Gaps:** un stop no puede asumir fill al precio stop cuando la apertura fue peor.
- **Capital:** cada cartera tiene un modelo explícito (`FIXED_NOTIONAL_EXPERIMENT` o `SELF_FINANCING_PORTFOLIO`).
- **No solapamiento:** una cartera one-slot no reutiliza capital antes del cierre de la operación previa.
- **Drawdown:** el capital inicial forma parte del running peak.
- **Experimentos aislados:** cada resultado contiene `experiment_id/run_id`; los IDs de candidatos son globalmente únicos.
- **Validation no es test:** una muestra usada para seleccionar candidatos no puede presentarse como test final.
- **Múltiples pruebas:** toda búsqueda de parámetros registra cuántas hipótesis probó y ajusta la confianza.
- **Benchmark:** toda estrategia se compara contra alternativas predefinidas y con exposición comparable.
- **Incertidumbre:** no se aprueba por un umbral puntual sin intervalos o estabilidad suficiente.

## 5. Invariantes de ejecución no negociables

- Si falla la lectura de cuenta, posiciones, reloj, órdenes pendientes o límites, no se envían órdenes.
- Un notional ausente, cero, negativo o no finito invalida la señal; nunca se reemplaza por el máximo permitido.
- Los límites de posiciones, órdenes diarias, exposición, pérdida y concentración se recalculan antes de cada envío.
- Toda intención se persiste antes de llamar al broker mediante un patrón outbox o state machine equivalente.
- Toda orden usa una idempotency key estable y se reconcilia por `client_order_id`.
- Una orden aceptada por el broker pero no persistida debe recuperarse automáticamente por reconciliación.
- Precios o quotes faltantes o stale no pueden provocar entradas o salidas.
- Debe existir kill switch global, por estrategia, por activo y por cuenta.
- Ninguna posición no administrada puede cerrarse o modificarse automáticamente.

## 6. Datos y contratos

Toda tabla crítica debe declarar:

- granularidad;
- clave primaria lógica;
- columnas temporales (`event_time`, `available_at`, `ingested_at`);
- fuente y versión;
- zona horaria;
- política de deduplicación;
- política de corporate actions;
- política de retención;
- assertions de nulidad, unicidad y dominio;
- productores y consumidores.

Las migraciones deben ser aditivas primero. No eliminar columnas ni reinterpretar su significado sin una ventana de compatibilidad y un plan de backfill.

## 7. Pruebas mínimas por tipo de cambio

### Datos point-in-time

- filing publicado después del cierre del periodo;
- revisión/restate de un filing;
- dos fuentes con timestamps distintos;
- fila futura que debe quedar excluida;
- cálculo YoY sobre trimestres deduplicados.

### Precios

- split;
- dividendo;
- día con 1d e intradía duplicados;
- sesión incompleta;
- timezone y DST;
- gap bajo stop;
- stop y take profit tocados en la misma vela.

### Strategy Brain

- IDs únicos entre corridas del mismo día;
- aislamiento por `run_id`;
- drawdown desde capital inicial;
- `best_eligible` distinto de `best_overall`;
- test final no reutilizado;
- resultados determinísticos con mismo snapshot y configuración.

### Executor

- fallo al consultar posiciones;
- límite alcanzado durante el loop;
- notional inválido;
- timeout después de aceptación del broker;
- retry con mismo `client_order_id`;
- quote faltante o stale;
- kill switch activo.

## 8. Evidencia requerida para cerrar una tarea

Una tarea solo está completa si la PR incluye:

- requerimiento y riesgo cubierto;
- archivos y contratos modificados;
- migración/backfill y rollback;
- pruebas añadidas;
- comandos ejecutados y exit codes;
- resultados cuantitativos antes/después cuando aplique;
- impacto en tablas, schedulers y costos;
- limitaciones no verificadas;
- actualización de `docs/audit-grade/08_traceability_matrix.md`.

Compilar o desplegar no equivale a demostrar corrección.

## 9. Prohibiciones

- No inventar métricas, filas, resultados ni evidencia.
- No ocultar fallos con retries silenciosos.
- No cambiar thresholds para hacer pasar una prueba.
- No usar datos actuales para rellenar historia sin una marca explícita de proxy.
- No permitir que un LLM autoapruebe su propia recomendación.
- No guardar secretos, tokens, webhooks o credenciales en código, fixtures, logs o artefactos.
- No modificar `main/master`, desplegar, fusionar ni alterar recursos live salvo autorización explícita.
- No declarar “listo para dinero real” únicamente por passing tests o un backtest positivo.

## 10. Fuente de verdad

El orden de precedencia es:

1. Requisitos explícitos del usuario.
2. Este `AGENTS.md`.
3. `docs/audit-grade/09_release_and_promotion_gates.md`.
4. Contratos y estándares de `docs/audit-grade/`.
5. Convenciones existentes del repositorio.

Cuando exista contradicción, mantener el sistema en el estado más seguro y documentar la decisión.
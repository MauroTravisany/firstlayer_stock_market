# 10 — Operabilidad, SLO y runbooks

## 1. Objetivo

La plataforma debe detectar, contener y recuperar fallos sin contaminar resultados ni enviar órdenes bajo estado desconocido.

## 2. Correlation IDs

Cada flujo usa y propaga:

```text
request_id
ingestion_run_id
data_snapshot_id
experiment_id
signal_id
order_intent_id
broker_order_id
reconciliation_run_id
```

Los logs estructurados permiten navegar end-to-end.

## 3. SLO propuestos

Los objetivos definitivos se calibran con operación, pero deben existir explícitamente.

### Datos

- freshness por fuente y asset class;
- porcentaje de sesiones esperadas completas;
- tasa de mismatches entre fuentes;
- porcentaje de filas con `available_at` verificable;
- cero violaciones point-in-time materiales;
- tiempo de publicación de snapshot aprobado.

### Transformaciones

- Dataform success rate;
- duración;
- bytes procesados/costo;
- assertions fallidas;
- lineage completeness.

### Research

- experiment completion rate;
- reproducibility success rate;
- checksum mismatch rate;
- runtime/costo por experimento;
- porcentaje de resultados con reporte completo.

### Señales

- señal generada dentro de ventana esperada;
- porcentaje con snapshot/config lineage completo;
- porcentaje degradado/rechazado por datos;
- drift de distribución de features/scores.

### Paper execution

- order intent -> broker accepted latency;
- reconciliation lag;
- order/position mismatch rate;
- duplicate order rate = 0;
- untracked position rate = 0;
- risk limit violation rate = 0;
- quote stale rejection rate;
- kill switch activation/clearance.

## 4. Error budgets

Cuando un SLO material agota su error budget:

- congelar nuevas features/optimización;
- priorizar reliability;
- pausar señales o entradas según dominio;
- abrir incidente y postmortem.

## 5. Alertas

### P0

- broker/internal position mismatch;
- orden broker-only;
- duplicado;
- policy ejecutable no autorizada;
- look-ahead audit failure;
- kill switch no respetado;
- secret exposure;
- pérdida de snapshot/ledger.

Acción: pausa inmediata de entradas y escalamiento.

### P1

- fuente crítica stale;
- corporate action mismatch;
- Dataform failure;
- reconciliation lag;
- scheduler no ejecutado;
- dashboard/report desactualizado;
- costo anómalo.

### P2

- warning de cobertura;
- degradación de fuente secundaria;
- performance drift no crítico;
- deuda documental.

## 6. Health y readiness

Cada servicio expone:

```text
/healthz   proceso vivo
/readyz    dependencias y configuración aptas
/version   git sha, image digest, config version sin secretos
```

El executor `readyz` incluye:

- modo paper;
- kill switch;
- reconciliación reciente;
- broker reachable;
- config válida;
- tablas disponibles.

## 7. Runbook: fuente de precios stale

1. Pausar publicación del snapshot.
2. Confirmar scheduler y logs.
3. Consultar fuente primaria/secundaria.
4. Comparar última sesión y timezone.
5. No rellenar con precio actual retroactivo.
6. Reejecutar ingesta con nuevo `ingestion_run_id`.
7. Ejecutar contracts/reconciliation.
8. Publicar nuevo snapshot solo si pasa gates.
9. Documentar gap y activos afectados.

## 8. Runbook: corporate action mismatch

1. Bloquear ticker para nuevas señales.
2. Comparar fuentes y fechas ex/record/pay.
3. Verificar raw vs adjusted series.
4. Corregir mediante nueva revisión, no overwrite silencioso.
5. Crear nuevo data snapshot.
6. Invalidar experimentos afectados.
7. Reproducir y comparar resultados.

## 9. Runbook: fallo point-in-time

1. Marcar snapshot inválido.
2. Pausar Strategy Brain y señales dependientes.
3. Identificar primera/última fecha afectada.
4. Corregir `available_at`/join.
5. Añadir regression test.
6. Backfill versionado.
7. Reejecutar experimentos.
8. Etiquetar resultados previos invalidated.
9. Publicar postmortem.

## 10. Runbook: Dataform failure

1. Revisar compilation result y assertion.
2. Determinar si es schema, datos, permisos o costo.
3. No actualizar release activo si compile falla.
4. Reintentar solo step idempotente.
5. Rollback a compilation result anterior.
6. Verificar tablas/snapshots antes de habilitar downstream.

## 11. Runbook: orden con estado ambiguo

1. Activar pausa de entradas.
2. Buscar por `client_order_id` en broker.
3. Comparar intent, order y fills.
4. No reenviar con ID nuevo.
5. Persistir broker state recuperado.
6. Ejecutar reconciliación.
7. Resolver o escalar manualmente.
8. Añadir regression test si el caso no estaba cubierto.

## 12. Runbook: broker/internal mismatch

1. Kill switch `PAUSED_RECONCILIATION`.
2. Capturar account/positions/orders/fills snapshots.
3. Clasificar finding.
4. No cerrar posiciones no administradas automáticamente.
5. Reconciliar órdenes conocidas.
6. Intervención humana para broker-only position.
7. Limpiar switch solo con evidencia y owner.

## 13. Runbook: pérdida diaria/drawdown excedido

1. Activar risk pause.
2. Bloquear entradas.
3. Mantener monitoreo de posiciones existentes.
4. Aplicar política de salida predefinida, no improvisada.
5. Verificar datos/quotes/broker.
6. Emitir incidente y reporte.
7. Requiere aprobación humana para reanudar.

## 14. Runbook: backfill

Todo backfill especifica:

- fuente y rango;
- tablas objetivo;
- `ingestion_run_id`;
- modo dry-run;
- estimación de costo;
- deduplicación;
- contracts;
- checksum antes/después;
- snapshot nuevo;
- consumidores afectados;
- rollback.

Nunca borrar historia para “limpiar” un backfill.

## 15. Runbook: rollback de release

1. Detener promoción/schedulers afectados.
2. Volver al image digest/Dataform result anterior.
3. Mantener migraciones aditivas compatibles.
4. Ejecutar smoke tests.
5. Confirmar que no quedaron órdenes/experimentos a medio estado.
6. Registrar release incident.

## 16. Disaster recovery

Definir y probar:

- RPO por tabla;
- RTO por servicio;
- retención y time travel;
- export/backups de contratos, configs y experiment registry;
- restauración en entorno aislado;
- reconstrucción de un experimento y una reconciliación.

## 17. Postmortem

Todo incidente P0/P1 incluye:

```text
summary
impact
timeline
detection
root cause
contributing factors
what worked
what failed
corrective actions
regression tests
owners/dates
```

No culpar personas; corregir sistemas y controles.

## 18. Criterios de aceptación

- cada alerta material tiene runbook;
- drills ejecutados y evidenciados;
- servicios exponen health/readiness/version;
- correlation IDs trazan un flujo completo;
- SLOs y error budgets visibles;
- fallos de datos pausan publicación;
- fallos de reconciliación pausan entradas;
- rollback y restore se han probado en entorno aislado.
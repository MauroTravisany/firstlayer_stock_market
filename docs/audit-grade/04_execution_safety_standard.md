# 04 — Estándar de seguridad de ejecución

## 1. Alcance

Este estándar aplica al executor de entradas, monitor de riesgo, órdenes de salida, sincronización con Alpaca Paper y cualquier futura integración de broker.

Hasta completar los gates, el único entorno permitido es Alpaca Paper.

## 2. Principio fail-closed

Ante cualquiera de estas condiciones no se envían nuevas órdenes:

- no se pudo leer la cuenta;
- no se pudieron leer posiciones;
- no se pudieron leer órdenes abiertas;
- no se pudo leer el reloj/calendario requerido;
- no se pudo leer o validar el quote;
- estado interno y broker no concuerdan;
- kill switch activo;
- data snapshot degradado o stale;
- política no aprobada;
- límites no calculables;
- notional/qty inválido;
- tabla outbox no disponible.

Un error de dependencia nunca se interpreta como “cero posiciones”, “sin órdenes” o “precio cero”.

## 3. State machine de órdenes

Tabla `order_intents`:

```text
CREATED
RISK_APPROVED
SUBMISSION_PENDING
BROKER_ACCEPTED
PARTIALLY_FILLED
FILLED
CANCEL_PENDING
CANCELED
REJECTED
EXPIRED
RECONCILIATION_REQUIRED
FAILED_SAFE
```

Transiciones válidas se implementan explícitamente. No actualizar estados arbitrariamente.

### Flujo de entrada

```text
1. Leer señal aprobada e idempotente.
2. Crear order_intent persistido.
3. Capturar snapshot de cuenta/posiciones/órdenes/quote.
4. Ejecutar risk gate.
5. Marcar RISK_APPROVED.
6. Marcar SUBMISSION_PENDING.
7. Enviar a Alpaca con client_order_id estable.
8. Persistir respuesta.
9. Reconsultar por client_order_id ante timeout/ambigüedad.
10. Reconciliar hasta estado terminal.
```

Si falla el paso 8 después de aceptación, el reconciliador debe recuperar la orden.

## 4. Idempotencia

```text
order_intent_id = UUID
client_order_id = deterministic hash(environment|account|order_intent_id)
```

Reglas:

- nunca generar otro `client_order_id` para el retry de la misma intención;
- antes de reenviar, consultar broker por el ID;
- una señal solo crea una intención activa;
- MERGE/unique constraints bloquean duplicados;
- salidas también son idempotentes por posición + reason + policy version.

## 5. Risk gate antes de cada orden

Recalcular en cada iteración:

- posiciones abiertas;
- órdenes abiertas;
- slots restantes;
- exposición bruta y neta;
- exposición por ticker/sector/asset type;
- órdenes enviadas en fecha real del broker;
- pérdida diaria/semana;
- drawdown paper;
- cash/buying power;
- stale quote age;
- health de servicios y reconciliación.

No basta con validar una vez antes del loop.

## 6. Validación numérica

Rechazar cuando:

```text
notional is None
notional <= 0
notional is NaN/Inf
qty <= 0
entry/stop/target <= 0
stop >= entry para long
risk_per_trade <= 0 o fuera de límites
```

Nunca reemplazar notional inválido por `max_notional_usd`.

## 7. Límites configurables

Configuración versionada y almacenada fuera del código:

```text
max_open_positions
max_pending_orders
max_orders_per_run
max_orders_per_broker_day
max_notional_per_order
max_gross_exposure
max_ticker_exposure
max_sector_exposure
max_crypto_exposure
max_daily_loss
max_weekly_loss
max_drawdown
max_slippage_bps
max_quote_age_seconds
max_reconciliation_age_seconds
```

La configuración efectiva y su hash se guardan en cada `risk_decision`.

## 8. Quotes y precios

- usar quote/trade apropiado al activo;
- validar timestamp;
- rechazar quote stale;
- no transformar ausencia en cero;
- registrar bid/ask/mid/last usados;
- medir slippage contra benchmark de ejecución;
- para equities, respetar market hours y tipo de orden;
- para cripto, tratar 24/7 y pares Alpaca de forma explícita.

## 9. Entradas equity

Antes de usar bracket:

- verificar que stop y take profit no son nulos;
- validar tick size y precisión;
- validar qty soportada/fractional rules;
- recalcular niveles con quote actual si la política lo exige;
- cancelar si el gap invalida la relación riesgo/beneficio;
- no enviar market order si el spread supera límite.

## 10. Entradas cripto

- confirmar que el activo y par son soportados;
- usar notional/qty compatible con Alpaca;
- validar precisión;
- límites separados de equities;
- monitor 24/7;
- fees/slippage específicos;
- no reutilizar supuestos de horario o TIF de equities.

## 11. Salidas

Prioridad explícita:

1. kill switch / forced risk exit;
2. stop loss;
3. policy invalidation si está definido;
4. take profit;
5. time exit;
6. manual intervention.

Una posición sin quote válido queda `RECONCILIATION_REQUIRED`; no se fuerza un precio cero.

## 12. Reconciliación

### Frecuencia

- después de cada envío;
- scheduler periódico;
- al inicio de cada ejecución;
- antes de permitir nuevas entradas;
- cierre diario.

### Comparaciones

```text
internal intent vs broker order
internal order vs broker fills
internal positions vs broker positions
internal cash/equity vs broker account
open exits vs active positions
```

### Findings

```text
MATCHED
BROKER_ONLY_ORDER
INTERNAL_ONLY_ORDER
BROKER_ONLY_POSITION
INTERNAL_ONLY_POSITION
STATUS_MISMATCH
QTY_MISMATCH
FILL_MISMATCH
STALE_INTERNAL_STATE
```

Cualquier finding material activa kill switch de entradas.

## 13. Kill switches

Niveles:

- global;
- broker account;
- asset class;
- strategy;
- ticker.

Estados:

```text
ACTIVE
PAUSED_MANUAL
PAUSED_RISK
PAUSED_DATA
PAUSED_RECONCILIATION
PAUSED_DEPENDENCY
```

Solo una acción humana autorizada puede limpiar pausas materiales, después de registrar causa y evidencia.

## 14. Auditoría

Cada decisión de riesgo registra:

```text
risk_decision_id
order_intent_id
decision_timestamp
policy_version
config_hash
account_snapshot_id
positions_snapshot_id
orders_snapshot_id
quote_snapshot_id
checks_json
decision APPROVE|REJECT|PAUSE
reason_codes
```

No guardar secretos ni payloads sensibles innecesarios.

## 15. Manejo de errores

- timeouts acotados;
- retries con backoff y jitter;
- circuit breaker para broker/dependencias;
- DLQ o tabla de recuperación para eventos no procesados;
- alertas para estado ambiguo;
- ningún retry ciego de POST sin reconciliación por idempotency key.

## 16. Pruebas obligatorias

### Unitarias

- notional inválido;
- límites por orden/posición;
- precisión y tick size;
- state transitions;
- stale quote;
- kill switch.

### Contrato con fake broker

- accepted;
- rejected;
- timeout antes de aceptación;
- timeout después de aceptación;
- partial fill;
- duplicate client_order_id;
- canceled/expired;
- position query failure;
- account query failure.

### Integración Paper

- dry-run sin mutación;
- una entrada mínima controlada en cuenta Paper aislada;
- reconciliación completa;
- salida por stop/TP/time en escenario preparado;
- cero órdenes duplicadas tras retry.

## 17. Criterios para habilitar `PAPER_CHAMPION`

- executor y monitor pasan toda la suite;
- reconciliación sin findings críticos;
- kill switches probados;
- límites recalculados por orden;
- no existe fallback de notional a máximo;
- toda dependencia crítica falla cerrada;
- outbox y recuperación demostrados;
- cuenta Paper separada de cualquier uso manual;
- runbook de incidentes aprobado;
- aprobación humana versionada.

## 18. Dinero real

La existencia de un executor seguro para Paper no habilita dinero real. Live requiere un proyecto separado, revisión de cumplimiento, broker/account configuration específica, threat model, controles humanos adicionales y gates operativos prolongados.
# 09 — Gates de release y promoción

## 1. Principio

La promoción es una state transition controlada, no una conclusión narrativa. Cada gate requiere evidencia independiente. Un gate posterior no compensa un gate anterior fallido.

```text
RESEARCH -> BACKTEST -> SHADOW -> PAPER -> LIVE_CANARY -> LIVE_APPROVED
```

El estado actual permitido durante la transformación es `BACKTEST_ONLY` y `SHADOW_ONLY`.

## 2. Roles separados

- **Implementer:** escribe el cambio.
- **Verifier:** revisa pruebas/evidencia independientemente.
- **Quant reviewer:** valida metodología y resultados.
- **Operational approver:** valida executor, observabilidad y runbooks.
- **Owner:** aprueba la transición.

La misma salida de IA no puede ocupar ninguno de estos roles.

## Gate G0 — Baseline preservado

### Requisitos

- commit, configuración y resultados legacy registrados;
- defectos conocidos asociados;
- `promotion_eligible = FALSE`;
- policy actual confirmada `SHADOW_ONLY`;
- rollback/base de comparación disponible.

### Resultado permitido

Continuar implementación.

## Gate G1 — Datos confiables

### Requisitos

- contratos machine-readable;
- point-in-time audit con cero violaciones materiales;
- corporate actions validadas;
- serie canónica sin mezcla de granularidad;
- source reconciliation dentro de tolerancia;
- universe versionado;
- snapshot inmutable y checksum;
- freshness/quality gates.

### Hard stop

Cualquier look-ahead, mismatch material no explicado o snapshot no reproducible.

### Resultado permitido

Backtesting audit-grade.

## Gate G2 — Simulación correcta

### Requisitos

- siguiente apertura;
- gaps y stops realistas;
- time exits por sesión;
- costos versionados y stress;
- modelo de capital explícito;
- drawdown desde capital inicial;
- no solapamiento/cash invariants;
- ledger y equity checksums;
- golden tests.

### Resultado permitido

Validación cuantitativa.

## Gate G3 — Validez cuantitativa

### Requisitos

- protocolo pre-registrado;
- nested walk-forward;
- purging/embargo;
- final locked test;
- benchmark predefinido;
- incertidumbre e intervalos;
- ajuste por múltiples pruebas;
- estabilidad por fold/año/activo/régimen;
- sensibilidad a costos/parámetros;
- evidencia no concentrada;
- verifier independiente.

### Estados posibles

```text
REJECTED
INSUFFICIENT_EVIDENCE
OUT_OF_SAMPLE_SUPPORTED
```

### Resultado permitido

Solo `OUT_OF_SAMPLE_SUPPORTED` puede avanzar a shadow.

## Gate G4 — Shadow readiness

### Requisitos

- servicio de señales consume snapshots aprobados;
- `execution_eligible = FALSE` técnicamente enforced;
- señal, features, configuración y lineage trazables;
- alertas/freshness/quality operativas;
- zero silent failures;
- runbooks y owners;
- política versionada.

### Periodo mínimo de observación

No fijar solo tiempo. Requerir simultáneamente:

- cobertura de varios regímenes o eventos relevantes;
- suficiente número de señales para evaluar drift;
- al menos un ciclo operativo sostenido sin incidentes críticos;
- criterio pre-registrado por frecuencia de estrategia.

Como referencia operacional, usar meses, no días, para estrategias de baja frecuencia.

### Resultado permitido

`PAPER_CANDIDATE` después de revisión.

## Gate G5 — Executor Paper readiness

### Requisitos

- state machine/outbox;
- persist-before-send;
- idempotencia/retry/reconciliation;
- fail-closed en dependencias;
- risk limits por orden;
- quote freshness/spread checks;
- kill switches;
- fake broker suite verde;
- integración Alpaca Paper controlada;
- cero posiciones/órdenes no rastreadas;
- security/IAM/runbooks aprobados.

### Resultado permitido

La infraestructura puede ejecutar una estrategia Paper aprobada.

## Gate G6 — Paper strategy readiness

### Requisitos cuantitativos y operativos

- estrategia pasó G3 y G4;
- paper fills reconciliados;
- slippage real dentro o peor que el modelo pero dentro del stress aprobado;
- diferencia señal->orden->fill explicada;
- límites respetados siempre;
- cero duplicados;
- cero untracked positions;
- drawdown paper dentro del budget pre-registrado;
- resultado no depende de un único evento;
- evidencia suficiente por frecuencia.

### Criterio de muestra

Definir antes de comenzar paper. Debe combinar:

- calendario mínimo;
- número mínimo de señales/fills;
- exposición a distintos regímenes;
- cero incidentes críticos abiertos.

Una estrategia con pocas señales no puede acelerar el gate reduciendo arbitrariamente la muestra.

### Resultado permitido

`PAPER_CHAMPION` o mantener/rechazar.

## Gate G7 — Platform live readiness

Este gate evalúa plataforma, no estrategia.

### Requisitos

- entornos separados;
- CI/deploy protegido;
- infraestructura como código;
- least privilege/WIF;
- secrets rotation;
- SLO/error budgets;
- DR/restore test;
- threat model;
- reconciliation y kill switches probados;
- compliance/legal/broker constraints revisados;
- human approval workflow;
- audit trail inmutable.

### Resultado permitido

La plataforma podría soportar un canary, pero aún no autoriza una estrategia.

## Gate G8 — Live canary strategy readiness

### Requisitos

- plataforma pasó G7;
- estrategia pasó G6;
- risk budget canary aprobado externamente;
- exposición estrictamente limitada;
- límites de pérdida más conservadores que Paper;
- manual kill switch probado;
- monitoreo humano durante ventanas definidas;
- rollback/cierre forzado probado;
- aprobación humana explícita con fecha/owner.

### Resultado permitido

`LIVE_CANARY` únicamente.

## Gate G9 — Live approved

### Requisitos

- evidencia canary prolongada y reconciliada;
- sin incidentes críticos;
- modelo de costos calibrado con fills reales;
- estrategia mantiene comportamiento esperado;
- riesgos y drawdowns dentro del budget;
- nueva aprobación independiente;
- documentación y scorecard actualizadas.

### Resultado permitido

`LIVE_APPROVED` con límites definidos. No existe promoción automática.

## 3. Gates de release de software

Toda versión de software pasa:

```text
CODE_COMPLETE
FOCUSED_TESTS_PASS
FULL_CI_PASS
SECURITY_SCAN_PASS
MIGRATION_DRY_RUN_PASS
STAGING_DEPLOY_PASS
SMOKE_PASS
APPROVAL
PROD_RESEARCH/PAPER DEPLOY
POST_DEPLOY_VERIFY
```

Un release de software no cambia la promoción de una estrategia.

## 4. Evidencia de gate

Tabla `promotion_gate_decisions`:

```text
decision_id
subject_type PLATFORM|STRATEGY|POLICY|RELEASE
subject_id
from_state
to_state
gate_id
evidence_manifest_uri
evidence_checksum
verifier
quant_reviewer
operational_approver
owner_approver
decision APPROVE|REJECT|DEFER
reason_codes
created_at
expires_at
```

Las aprobaciones pueden expirar cuando cambian código, datos, configuración o broker.

## 5. Invalidación automática de evidencia

Requiere revalidación cuando cambia:

- feature set;
- estrategia o parámetros;
- universo;
- cost/execution model;
- data source o corporate-action logic;
- broker/adapter;
- risk policy;
- dependencia material;
- metodología de test;
- incidente crítico.

## 6. Reglas absolutas

- backtest positivo no salta a paper;
- paper positivo no salta a live;
- pasar CI no significa pasar un gate cuantitativo;
- una IA no aprueba gates;
- una aprobación sin evidence checksum es inválida;
- todo estado puede retroceder por data/risk/operational finding;
- ante duda material, mantener el estado más seguro.
# FirstLayer Stock Market

Plataforma personal de investigación cuantitativa, análisis de cartera, generación de señales, backtesting, alertas y ejecución controlada en **Alpaca Paper** sobre Google Cloud.

> **Estado de seguridad:** las políticas de champion/challenger deben permanecer en `SHADOW_ONLY` mientras se implementa y verifica el programa audit-grade. El repositorio no autoriza dinero real ni promoción automática de estrategias.

## Objetivos

- Recolectar precios, fundamentales, earnings, macro y contexto externo.
- Transformar datos en series y features reproducibles con Dataform/BigQuery.
- Analizar valoración, calidad, momentum, riesgo y cambios de estado.
- Comparar estrategias mediante backtesting con costos y capital separado.
- Probar hipótesis y candidatos sin modificar reglas ejecutables.
- Generar análisis IA y alertas con trazabilidad.
- Validar operación únicamente en Alpaca Paper bajo controles de riesgo.

## Programa audit-grade

El repositorio contiene una especificación completa para elevar la plataforma a un estándar auditable y reproducible:

- [Programa de transformación](docs/audit-grade/README.md)
- [Arquitectura objetivo](docs/audit-grade/01_target_architecture.md)
- [Contratos point-in-time](docs/audit-grade/02_data_contracts_and_point_in_time.md)
- [Validación cuantitativa](docs/audit-grade/03_quant_validation_standard.md)
- [Seguridad del executor](docs/audit-grade/04_execution_safety_standard.md)
- [Pruebas, CI y reproducibilidad](docs/audit-grade/05_testing_ci_reproducibility.md)
- [Backlog de implementación](docs/audit-grade/06_implementation_backlog.md)
- [Prompts secuenciales para Codex](docs/audit-grade/07_codex_execution_prompts.md)
- [Matriz de trazabilidad](docs/audit-grade/08_traceability_matrix.md)
- [Gates de promoción](docs/audit-grade/09_release_and_promotion_gates.md)
- [Operabilidad y runbooks](docs/audit-grade/10_operability_runbooks.md)
- [Scorecard 10/10](docs/audit-grade/11_scorecard_10_of_10.md)
- [Optimización por activo](docs/audit-grade/12_per_asset_optimization_protocol.md)

Cualquier agente de código debe leer [AGENTS.md](AGENTS.md) antes de modificar el repositorio.

## Arquitectura actual

```text
Yahoo Finance / GDELT / Alpaca Paper / OpenAI
                    |
                    v
Cloud Run services
  - stockdaily
  - stockmacrodata
  - stockfinancial
  - stockaianalysis
  - papertradingalerts
  - strategybrain
  - paper trade executor
  - paper risk monitor
                    |
                    v
BigQuery + Cloud Storage
                    |
                    v
Dataform
  - valoración y estados de empresa
  - features de precio y contexto
  - señales V1–V4
  - backtesting y curvas
  - champion/challenger
  - Strategy Brain
                    |
          +---------+----------+
          |                    |
          v                    v
Evidence dashboard       Discord/alertas
                               |
                               v
                         Alpaca Paper
```

## Componentes

### Ingesta de precios

`cloud-functions/daily_stocks/`

- acciones recientes e historia diaria;
- cripto con consolidación de frecuencia;
- carga idempotente en BigQuery;
- registro de calidad.

### Fundamentales

`cloud-functions/financial_data/`

- estados financieros trimestrales;
- ratios snapshots;
- calidad de cobertura;
- universo de cartera y peers.

### Macro, noticias y earnings

`cloud-functions/macro_data/`

- factores de mercado;
- noticias agregadas por tema;
- calendario/sorpresa de resultados;
- contexto reciente para análisis y señales.

### Análisis IA

`cloud-functions/daily_ai_analysis/`

- salida JSON estructurada;
- contraste externo mediante web search;
- análisis de compra, venta, riesgo y calidad de datos;
- resumen diario y semanal;
- almacenamiento de fuentes y confianza.

### Paper trading y alertas

`cloud-functions/paper_trading_alerts/`

- resumen de señales/resultados;
- feedback diario y revisión semanal;
- alertas Discord/webhook;
- sugerencias experimentales limitadas a backtest/shadow.

### Strategy Brain

`cloud-functions/strategy_brain/`

- genera candidatos acotados;
- evalúa resultados históricos;
- registra candidatos, generaciones y auditorías;
- nunca debe promover automáticamente una regla.

### Ejecución Paper

`cloud-functions/paper_trade_executor/`  
`cloud-functions/paper_trade_risk_monitor/`

- integración con Alpaca Paper;
- entradas y monitoreo de posiciones;
- stops, take profit y time exits;
- límites configurables y registros de ejecución.

El programa audit-grade exige outbox, reconciliación, fail-closed y kill switches antes de habilitar cualquier `PAPER_CHAMPION`.

### Dataform

`dataform/definitions/`

Contiene modelos para:

- perfiles de activos y peers;
- valoración y estados;
- features diarias;
- contexto macro/earnings;
- señales de paper trading;
- backtests direccionales y contextuales;
- Strategy Brain;
- champion/challenger;
- vistas de dashboard.

### Dashboard

`dashboard/`

Dashboard Evidence estático construido desde snapshots exportados desde BigQuery. Su publicación y exposición de datos debe revisarse como parte del programa de seguridad.

### Infraestructura

- `.github/workflows/`: CI/CD y schedulers configurados durante deploy.
- `terraform/`: infraestructura parcial actual.
- Google Cloud: Cloud Run, BigQuery, Cloud Storage, Secret Manager, Scheduler y Dataform.

## Estados de seguridad

| Estado | Uso |
|---|---|
| `RESEARCH_ONLY` | Investigación sin señales ejecutables. |
| `BACKTEST_ONLY` | Historia y experimentos. |
| `SHADOW_ONLY` | Señales actuales sin órdenes. |
| `PAPER_CANDIDATE` | Observación candidata. |
| `PAPER_CHAMPION` | Único estado potencialmente consumible por Alpaca Paper. |
| `LIVE_*` | No habilitado por este repositorio actualmente. |

## Principios no negociables

- Ningún backtest garantiza retornos futuros.
- Las estrategias V1–V4 mantienen capital independiente y no se suman.
- Toda información histórica debe respetar disponibilidad point-in-time.
- Ejecución y retornos deben distinguir precios raw/adjusted.
- Cada experimento debe fijar código, datos, configuración y metodología.
- La IA puede explicar o proponer hipótesis; no puede aprobar parámetros ni ejecución.
- Un deploy verde no demuestra validez cuantitativa.
- Un resultado positivo no autoriza paper ni dinero real.

## Verificación local básica

Mientras se implementa el nuevo CI, los checks mínimos existentes son:

```bash
python -m compileall -q \
  cloud-functions/daily_stocks \
  cloud-functions/financial_data \
  cloud-functions/macro_data \
  cloud-functions/daily_ai_analysis \
  cloud-functions/paper_trading_alerts \
  cloud-functions/paper_trade_executor \
  cloud-functions/paper_trade_risk_monitor \
  cloud-functions/strategy_brain
```

Dataform:

```bash
cd dataform
npm install
# La compilación completa requiere la herramienta/entorno Dataform configurado.
```

Dashboard:

```bash
cd dashboard
npm install --legacy-peer-deps
npm run sources:strict
npm run build:strict
```

No ejecutar deploys ni llamadas de broker desde una rama de desarrollo.

## Estructura

```text
.github/workflows/        CI/CD
auditoria_M*.md           auditorías históricas
cloud-functions/          servicios Cloud Run
dashboard/                Evidence dashboard
dataform/                  modelos BigQuery/Dataform
docs/                     documentación operativa
docs/audit-grade/         programa de transformación
looker_studio/            integración histórica de visualización
terraform/                infraestructura como código parcial
AGENTS.md                  reglas obligatorias para agentes
```

## Resultados históricos

Los resultados anteriores a la implementación completa de point-in-time, corporate actions, backtest realista, aislamiento de corridas y validación nested walk-forward deben tratarse como:

```text
LEGACY_PRE_AUDIT_GRADE
NOT_ELIGIBLE_FOR_PROMOTION
```

Se preservan para auditoría, pero deben recalcularse antes de usarlos como evidencia.

## Seguridad

- No guardar secretos, API keys, webhooks ni credenciales en el repositorio.
- Usar Secret Manager y, como objetivo, Workload Identity Federation.
- Mantener Alpaca en Paper.
- Mantener políticas ejecutables deshabilitadas hasta pasar los gates.
- Revisar [el estándar de ejecución](docs/audit-grade/04_execution_safety_standard.md) antes de tocar el broker.

## Aviso

Este proyecto es una plataforma de investigación y no constituye recomendación financiera personalizada. La calidad del sistema se mide por la corrección y auditabilidad del proceso, no por promesas de rentabilidad.
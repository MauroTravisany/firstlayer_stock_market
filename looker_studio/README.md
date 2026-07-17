# Looker Studio - Portfolio Dashboard

Este dashboard se conecta a BigQuery y usa vistas preparadas por Dataform.

## Fuentes de datos

Conectar estas vistas desde BigQuery:

```text
stocks-437902.acciones_dataset.looker_portfolio_latest
stocks-437902.acciones_dataset.looker_portfolio_history
stocks-437902.acciones_dataset.looker_portfolio_summary
stocks-437902.acciones_dataset.looker_portfolio_ai_summary
```

## Paginas sugeridas

### 1. Resumen cartera

Fuente principal: `looker_portfolio_summary`

Componentes:

- Score promedio de cartera: `avg_final_score`
- Conteo total: `ticker_count`
- Conteo por senal: `buy_watch_count`, `quality_fair_count`, `overvalued_count`, `high_risk_count`
- Serie temporal de `avg_final_score`
- Tabla pequena con `top_5_tickers` y `bottom_5_tickers`

### 2. Ranking diario

Fuente principal: `looker_portfolio_latest`

Componentes:

- Tabla por `ticker`
- Campos: `signal`, `classification`, `final_score`, `quality_score`, `momentum_score`, `risk_score`, `last_close`
- Filtros: `signal`, `classification`, `opportunity_bucket`
- Orden default: `final_score DESC`

### 3. Detalle por accion

Fuente principal: `looker_portfolio_latest`

Componentes:

- Control de filtro: `ticker`
- Scorecards: `final_score`, `valuation_score`, `quality_score`, `momentum_score`, `risk_score`
- Textos largos: `ai_summary`, `ai_analysis`, `ai_risks`, `ai_opportunity`, `ai_decision_support`
- Texto de fuentes: `external_sources_json`

### 4. Historial

Fuente principal: `looker_portfolio_history`

Componentes:

- Serie temporal `final_score` por `ticker`
- Serie temporal `last_close` por `ticker`
- Tabla de cambios: `ticker`, `analysis_date`, `previous_signal`, `signal`, `final_score_change`
- Filtro booleano: `signal_changed`

### 5. Resumen IA diario

Fuente principal: `looker_portfolio_ai_summary`

Componentes:

- Tarjeta de texto: `dashboard_summary`
- Tarjeta de texto: `top_opportunities`
- Tarjeta de texto: `overvalued_summary`
- Tarjeta de texto: `risk_summary`

## Estilo recomendado

- Tema claro.
- Verde para `COMPRAR_OBSERVAR`.
- Azul para `CALIDAD_ALTA_PRECIO_JUSTO`.
- Gris para `MANTENER`.
- Rojo para `SOBREVALORADA`.
- Naranjo para `RIESGO_ALTO` y `TRAMPA_DE_VALOR`.

## Nota operativa

Las vistas se actualizan automaticamente cuando corre Dataform. Looker Studio solo debe refrescar las fuentes.

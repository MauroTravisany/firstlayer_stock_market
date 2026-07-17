# Daily AI Analysis

Servicio Cloud Run que lee `portfolio_daily_signal`, genera analisis por ticker con IA y busqueda web controlada, guarda el resultado en BigQuery y envia una alerta corta por Slack o Discord si hay webhook configurado.

## Tablas BigQuery

```text
acciones_dataset.portfolio_ai_analysis_daily
acciones_dataset.portfolio_ai_summary_daily
```

## Secretos requeridos

```text
OPENAI_API_KEY
```

## Secretos opcionales para alertas

```text
ALERT_WEBHOOK_URL
```

Variables opcionales:

```text
OPENAI_MODEL=gpt-5-mini
ALERT_WEBHOOK_TYPE=auto|slack|discord
PROMPT_VERSION=portfolio-ai-v1
```

## Ejecucion

El scheduler debe ejecutarse despues de Dataform, por ejemplo a las 20:45 America/Santiago.

Payload normal:

```json
{}
```

Payload de prueba sin IA:

```json
{"dry_run": true}
```

Payload filtrando ticker:

```json
{"tickers": ["AAPL"], "send_alert": false}
```

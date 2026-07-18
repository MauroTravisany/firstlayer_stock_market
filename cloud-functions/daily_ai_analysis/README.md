# Daily AI Analysis

Servicio Cloud Run que lee `portfolio_daily_signal`, genera analisis por ticker con IA y busqueda web controlada, guarda el resultado en BigQuery y envia una alerta corta por Slack o Discord si hay webhook configurado.

El analisis cubre:

- oportunidades claras de compra;
- empresas caras o con posible venta;
- riesgos fundamentales, momentum y discrepancias externas.

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

## Alertas

Compra clara:

```text
signal = COMPRAR_OBSERVAR
final_score >= 6.0
confidence_score >= 0.65
```

Venta clara:

```text
sell_signal = VENTA_CLARA o signal = VENDER_OBSERVAR
sell_score >= 7.0
confidence_score >= 0.65
```

Si no hay compra o venta clara, el analisis se guarda en BigQuery pero no se envia alerta.

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

# Paper Trading

Modulo de simulacion. No ejecuta dinero real.

Watchlist inicial:

- AAPL
- MSFT
- NVDA
- META
- COIN
- BTC-USD
- ETH-USD

Supuestos iniciales:

- Capital ficticio: 10.000.000 CLP.
- Riesgo por trade: 1% del capital.
- Posicion maxima por trade: 20% del capital.
- USDCLP usado para simulacion: 950.
- Objetivo diario observado: 25.000 a 100.000 CLP.
- Acciones: datos diarios desde la tabla de precios.
- Cripto: usa velas de 4 horas consolidadas, agregadas a lectura diaria.
- Costos: spread + slippage estimados por activo.

El sistema genera senales `TRADE_LONG`, `VIGILAR` o `SIN_TRADE`. Para cada trade simulado guarda entrada teorica, stop loss, take profit, monto ficticio y resultado posterior. El resumen diario se envia por Discord una vez al dia de lunes a viernes.

La consistencia se mide por P&L ficticio, win rate, cantidad de trades cerrados y cantidad de trades abiertos. El objetivo no fuerza operaciones: si no hay setup, no se abre trade.

## Estrategias v1-v4

Las reglas estan versionadas en `trading_strategy_versions`:

- `v1`: base corto controlado, hasta 10 dias.
- `v2`: swing conservador, hasta 20 dias.
- `v3`: momentum swing, hasta 30 dias.
- `v4`: selectiva de mayor plazo, hasta 45 dias.

Cada version tiene su propio riesgo por trade, posicion maxima, stop por ATR, stop minimo, take profit y filtros. Esto permite comparar resultados sin mezclar reglas.

## Feedback IA

Al cierre del dia el servicio puede enviar el resumen de trades a un agente IA. El feedback queda guardado en `trading_ai_feedback_daily` e incluye:

- resumen ejecutivo,
- que funciono,
- que fallo,
- riesgos,
- sugerencias de parametros,
- informacion externa/noticias que conviene revisar,
- siguientes acciones.

La IA no modifica reglas automaticamente. Sus sugerencias se almacenan para revision y ajustes posteriores.

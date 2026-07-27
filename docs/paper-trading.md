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

El sistema genera senales `TRADE_LONG`, `VIGILAR` o `SIN_TRADE`. Para cada trade simulado guarda entrada teorica, stop loss, take profit, monto ficticio y resultado posterior.

El proceso de trading opera todos los dias. Los precios se refrescan cada 4 horas y Dataform recalcula las tablas cada 4 horas. Cada intento queda identificado por fecha, hora de slot, ticker y estrategia.

Discord se envia una vez al dia, a las 21:40 America/Santiago, con el resumen de todo lo ocurrido durante el dia. Esto evita ruido, pero mantiene el motor evaluando trades durante dia y noche.

La consistencia se mide por P&L ficticio, win rate, cantidad de trades cerrados y cantidad de trades abiertos. El objetivo no fuerza operaciones: si no hay setup, no se abre trade.

## Estrategias v1-v4

Las reglas estan versionadas en `trading_strategy_versions`:

- `v1`: base corto controlado, hasta 10 dias.
- `v2`: swing conservador, hasta 20 dias.
- `v3`: momentum swing, hasta 30 dias.
- `v4`: selectiva de mayor plazo, hasta 45 dias.

Cada version tiene su propio riesgo por trade, posicion maxima, stop por ATR, stop minimo, take profit y filtros. Esto permite comparar resultados sin mezclar reglas.

Desde la version intradia, una misma accion o cripto puede tener varios intentos en el mismo dia si aparecen setups en diferentes slots de 4 horas. El objetivo es comparar que estrategia funciona mejor por activo, horario y contexto macro.

## Perfil macro por activo

El paper trading ahora usa una capa de sensibilidad por activo en `trading_asset_macro_profile`.

Ejemplos:

- Semiconductores como `NVDA`: pesan mas ciclo growth, apetito por riesgo, tasas y riesgo geopolitico/cadena de suministro.
- Software mega cap como `MSFT`: pesa growth, tasas y fortaleza defensiva del negocio.
- Publicidad digital como `META`: pesa consumo/riesgo y ciclo de crecimiento.
- `COIN`: pesa mucho ciclo cripto, BTC/ETH y apetito especulativo.
- `BTC-USD` y `ETH-USD`: no usan fundamentales corporativos; pesan liquidez, dolar, tasas, ciclo cripto y apetito por riesgo.

El contexto de mercado vive en `trading_macro_context` y se calcula por bloques de 4 horas. Primero usa fuentes externas reales y, si faltan datos, cae a proxies internos usando precios ya cargados:

- mercado general, tecnologia/growth, defensivos, energia, tasas, dolar, euro, volatilidad, oro, petroleo, BTC y ETH,
- noticias por temas: conflictos geopoliticos, tasas/inflacion, dolar/divisas, regulacion crypto, semiconductores/IA y energia,
- fallback interno para no detener el proceso si una fuente externa falla.

`external_macro_data_status` indica si la senal uso datos externos completos, solo mercado, solo noticias o solo proxy.

El servicio `stockmacrodata` carga las tablas `macro_market_snapshot` y `macro_news_signal` cada 4 horas, 10 minutos despues de la carga de precios y antes del recalculo de Dataform.

La senal final combina:

- score tecnico ponderado por tipo de activo,
- ajuste macro segun sensibilidad del activo,
- reglas v1-v4 de riesgo, stop y horizonte.

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

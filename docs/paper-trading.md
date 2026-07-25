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

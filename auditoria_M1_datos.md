# Auditoria M1 - Datos y Fuentes

Fecha de auditoria: 2026-08-04

Alcance: fuentes de datos, cobertura, frecuencia, frescura, uniones y calidad observada en BigQuery. Este informe es solo documental. No modifica codigo, tablas, schedulers ni configuraciones.

## Dictamen ejecutivo

La serie principal de precios diaria esta correctamente homogeneizada y es apta como base para analisis diario desde 2019. Las fuentes fundamentales, de noticias y de resultados empresariales tienen cobertura mucho mas corta; deben tratarse como contexto reciente, no como evidencia historica completa para validar estrategias desde 2019.

## Inventario de fuentes

| Dominio | Fuente externa | Tabla principal | Uso actual |
|---|---|---|---|
| Precios de acciones y cripto | Yahoo Finance via yfinance | `valores_acciones_recientes` | OHLCV, retornos, tendencia, volumen y volatilidad |
| Ratios financieros | Yahoo Finance via yfinance | `financial_ratios_snapshot` | Valoracion y calidad de empresas |
| Estados financieros | Yahoo Finance via yfinance | `financial_statements` | Contexto financiero historico as-of-date |
| Factores macro | Yahoo Finance via yfinance | `macro_market_snapshot` | SPY, QQQ, VIX, dolar, tasas, petroleo, oro, BTC y ETH |
| Noticias macro | GDELT publico | `macro_news_signal` | Conteo de titulares por tema, no sentimiento semantico |
| Calendario y sorpresa de resultados | Yahoo Finance via yfinance | `macro_earnings_calendar` | Riesgo pre/post earnings |
| Perfiles y reglas | Definiciones Dataform manuales | `trading_watchlist`, perfiles macro/factoriales y estrategias | Universo, costos, sensibilidades y parametros |

## Frecuencia real y transformacion

- Acciones: el colector solicita 15 minutos en fechas recientes y diario fuera de la ventana soportada por Yahoo.
- Cripto: el colector solicita una hora y consolida a cuatro horas.
- La capa principal `trading_price_features` consolida todo a una vela diaria comparable: primera apertura, ultimo cierre, maximo, minimo y volumen acumulado.
- El backtest intradia esta separado. No rellena datos diarios como si fueran intradia.

Esta separacion evita mezclar ventanas tecnicas de 15 minutos con datos diarios historicos.

## Evidencia observada en BigQuery

| Fuente | Filas | Cobertura | Fecha mas reciente | Evaluacion |
|---|---:|---|---|---|
| Precios | 81.839 | 28 tickers, desde 2019-01-01 | 2026-08-04 | Apto para serie diaria |
| Ratios financieros | 979 | 75 tickers, desde 2026-07-15 | 2026-08-03 | Reciente, no historico largo |
| Estados financieros | 448 | 68 tickers, desde 2024-10-31 | 2026-06-30 | Periodico y con rezago natural |
| Macro mercado | 25.237 | 12 factores, desde 2019-01-01 | 2026-08-04 | Cobertura historica disponible |
| Noticias macro | 318 | 6 temas, desde 2026-07-26 | 2026-08-04 | Cobertura muy reciente |
| Earnings | 1.040 | 26 tickers, desde 2026-07-28 | 2026-08-04 | Cobertura muy reciente |

Control de unicidad de la serie principal: `trading_price_features` contiene 12.596 filas y 12.596 combinaciones distintas `analysis_date + ticker`, desde 2019-01-01 a 2026-08-04. No se detectaron duplicados diarios en esta capa.

## Cobertura del universo operativo

| Activo | Precio diario | Ratios | Estados financieros | Earnings | Situacion |
|---|---|---|---|---|---|
| AAPL | Hasta 2026-08-03 | Hasta 2026-08-03 | Periodo 2026-06-30 | Hasta 2026-08-04 | Completo para accion |
| NVDA | Hasta 2026-08-03 | Hasta 2026-08-03 | Periodo 2026-04-30 | Hasta 2026-08-04 | Estado financiero mas rezagado |
| META | Hasta 2026-08-03 | Hasta 2026-08-03 | Periodo 2026-06-30 | Hasta 2026-08-04 | Completo para accion |
| COIN | Hasta 2026-08-03 | Hasta 2026-08-03 | Periodo 2026-06-30 | Hasta 2026-08-04 | Completo para accion |
| BTC-USD | Hasta 2026-08-04 | No aplica | No aplica | No aplica | Correcto para cripto |
| ETH-USD | Hasta 2026-08-04 | No aplica | No aplica | No aplica | Correcto para cripto |
| MSFT | No entra a la capa activa | Datos disponibles | Datos disponibles | Datos disponibles | Deshabilitado intencionalmente |

El contexto macro reciente indica mercado y noticias externas disponibles en la mayoria de los dias revisados. Hubo dias con mercado externo disponible pero noticias faltantes. El sistema conserva un estado explicito para esa degradacion.

## Hallazgos

### M1-H1 - Earnings no valida el backtest historico completo

Severidad: Alta.

De 12.596 registros de contexto historico, 12.576 estan marcados `NO_EARNINGS_DATA`. Los eventos reales de resultados aparecen solo desde fines de julio de 2026. El modelo evita usar un evento futuro porque une datos as-of-date, pero el efecto de earnings no esta probado a traves del periodo 2019-2026.

Impacto: los resultados historicos no demuestran que la regla de earnings aumente el rendimiento. Es una proteccion operativa reciente, no una ventaja estadistica demostrada.

### M1-H2 - Noticias macro sin historia suficiente

Severidad: Alta.

GDELT tiene datos desde 2026-07-26. Para el periodo anterior, las reglas de contexto politico y noticioso usan proxies de mercado o quedan sin noticia externa.

Impacto: no debe atribuirse rendimiento historico a noticias, guerras o regulacion. Solo los factores de mercado diarios tienen cobertura historica continua.

### M1-H3 - Fundamentales con rezago y cobertura historica acotada

Severidad: Media.

Los ratios son snapshots recientes y los estados financieros siguen su frecuencia trimestral. El ultimo periodo disponible llega a 2026-06-30 para la mayor parte del universo y a 2026-04-30 para NVDA.

Impacto: esto es normal para fundamentales, pero un ratio no representa informacion intradia ni necesariamente incorpora un anuncio de resultados del mismo dia.

### M1-H4 - Dependencia concentrada en Yahoo Finance

Severidad: Media.

Precios, ratios, estados y earnings dependen de Yahoo Finance/yfinance. El sistema contiene monitoreo y estados de degradacion, pero no hay una fuente independiente de reconciliacion de precio o fundamentales.

Impacto: una respuesta parcial o inconsistente de Yahoo puede afectar varias capas a la vez.

### M1-H5 - Cobertura intradia desigual por activo

Severidad: Media.

El control intradia requiere 60 sesiones totales y 50 en los ultimos 90 dias. BTC y ETH cumplen con 132 sesiones totales y 90 recientes. AAPL registra 19 sesiones totales y 16 recientes, por lo que permanece en `COLLECTING`.

Impacto: las acciones no deben recibir conclusiones de backtest de cuatro horas hasta completar cobertura suficiente.

## Controles que funcionan correctamente

- El almacenamiento de precios usa identificador por ticker, fecha y hora, permitiendo merges idempotentes.
- La capa diaria consolidada elimina la mezcla de granularidades para indicadores de largo plazo.
- Las uniones fundamentales y de earnings historicos usan registros disponibles en o antes de la fecha analizada.
- El contexto macro expone estados de disponibilidad externa, en vez de ocultar faltantes.
- Cripto se trata sin ratios ni earnings corporativos, lo cual es semantica correcta.

## Conclusion M1

El sistema tiene una base de precios diaria solida para el periodo 2019-2026. La lectura fundamental es adecuada para analisis actual de empresas, con el rezago propio de reportes trimestrales. Macro de mercado tiene historia, mientras que noticias y earnings solo aportan informacion reciente. Cualquier evaluacion historica debe separar claramente: tecnica/precios si esta validada en toda la muestra; noticias, earnings y fundamentales no lo estan en la misma profundidad temporal.

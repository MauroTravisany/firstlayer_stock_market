# Auditoria M2 - Logica de Estrategias v1 a v4

Fecha de auditoria: 2026-08-04

Alcance: construccion de senales, parametros de v1-v4, evaluacion de resultados, controles de riesgo y riesgos metodologicos. Este informe es solo documental. No modifica codigo, tablas, schedulers ni configuraciones.

## Dictamen ejecutivo

Las cuatro estrategias no son cuatro algoritmos completamente distintos. Comparten el mismo motor tecnico, macro, factorial y de earnings; se diferencian por selectividad, tamano, riesgo y plazo de mantenimiento. La comparacion separada de capital es correcta, pero existe un hallazgo alto en la salida por tiempo de acciones que impide considerar los resultados como backtest final listo para dinero real.

## Flujo comun de todas las versiones

1. `trading_price_features` crea una vela diaria OHLCV por activo.
2. `trading_macro_context` construye regimen macro, miedo, riesgo, dolar, tasas, commodities y cripto.
3. `trading_earnings_context` agrega cercania y sorpresa de resultados cuando existe informacion.
4. Perfiles por activo convierten sensibilidad sectorial, macro y factorial en ponderaciones.
5. `trading_paper_signals` calcula tendencia, momentum, volumen, volatilidad, regimen, macro, factores, entrada, stop, objetivos, costo y tamano teorico.
6. `trading_paper_signals_active` puede reemplazar la senal base por una variante contextual solo cuando hay evidencia suficiente.
7. `trading_directional_signals` decide `LONG`, `SHORT_SIMULATED` o `NO_TRADE`.
8. `trading_directional_trade_results` evalua stop, objetivos o salida por tiempo.
9. `trading_directional_strategy_backtest` selecciona una sola posicion LONG a la vez por version y espera su cierre antes de elegir la siguiente.

Los shorts permanecen como diagnostico. No entran a la curva principal de capital ni a Alpaca Paper.

## Diferencias de parametros

| Version | Nombre | Riesgo por trade | Maximo por posicion | Score minimo | R/R minimo | Stop ATR | Horizonte | Filtros extra |
|---|---|---:|---:|---:|---:|---:|---:|---|
| v1 | Base corto controlado | 1,00% | 20% | 5 | 1,40 | 1,50 | 10 dias | Ninguno |
| v2 | Swing conservador | 0,80% | 18% | 6 | 1,60 | 1,70 | 20 dias | Tendencia fuerte |
| v3 | Momentum swing | 0,75% | 20% | 6 | 1,70 | 2,00 | 30 dias | Tendencia y volumen |
| v4 | Selectiva largo plazo | 0,60% | 15% | 7 | 1,90 | 2,20 | 45 dias | Tendencia, volumen y regimen positivo para cripto |

Las cuatro parten con $10.000.000 CLP simulados de manera independiente. El tamano teorico se calcula como el menor entre el limite de posicion y el importe compatible con el riesgo y distancia al stop.

## Resultado observado despues de normalizar la serie diaria

| Version | Cierres secuenciales | Win rate | PnL acumulado | Capital final teorico |
|---|---:|---:|---:|---:|
| v1 | 210 | 47,14% | +$1.611.165 CLP | $11.611.165 CLP |
| v2 | 127 | 43,31% | +$2.662.336 CLP | $12.662.336 CLP |
| v3 | 80 | 47,50% | +$2.428.761 CLP | $12.428.761 CLP |
| v4 | 63 | 42,86% | +$1.492.246 CLP | $11.492.246 CLP |

Periodo cubierto: enero de 2019 a agosto de 2026. Los montos son PnL teorico acumulado, no dinero real, no rendimiento anual y no una suma entre v1-v4.

## Lectura por version

### v1

Es la referencia mas amplia: entra con menor score, usa menor R/R y no exige tendencia ni volumen. Genera mas operaciones y mas cierres. Es util como linea base, pero tambien la mas expuesta a setups de menor calidad.

### v2

Exige tendencia fuerte y permite mas tiempo de desarrollo. Tiene menos cierres que v1, menor win rate, pero el mejor PnL acumulado del conjunto actual. Esto implica que sus ganancias medias compensan una frecuencia menor de aciertos. No basta para declararla ganadora definitiva sin corregir el hallazgo de salida por tiempo.

### v3

Agrega confirmacion de volumen y un horizonte mayor. Opera menos y busca momentum mas confirmado. Su win rate es el mayor del conjunto actual, aunque su PnL acumulado queda bajo v2.

### v4

Es la mas selectiva: mayor score, mayor R/R, menor riesgo y menor posicion. Opera menos. Su muestra es la mas pequena, por lo que su resultado tiene mayor incertidumbre estadistica.

## Controles positivos de diseno

- Las curvas de v1-v4 se calculan por separado; no se suman capitales incompatibles.
- El backtest principal selecciona una sola posicion LONG a la vez por estrategia, evitando reutilizar el mismo capital en senales solapadas.
- Los costos de spread y slippage entran en el calculo de retorno neto.
- El motor distingue LONG de SHORT_SIMULATED y excluye estos ultimos del capital principal.
- Las configuraciones contextuales activas tienen umbrales minimos de evidencia. Actualmente 15 combinaciones ticker-estrategia usan una configuracion activa; la mayor parte continua con la base.
- Los datos financieros y earnings se unen as-of-date, reduciendo riesgo de usar datos futuros directamente.

## Hallazgos de auditoria

### M2-H1 - Salida por tiempo de acciones no se ejecuta como se define

Severidad: Alta.

La evaluacion limita la ruta futura a `max_holding_days` dias calendario y, a la vez, exige observar al menos `max_holding_days` registros para declarar `TIME_EXIT`. En acciones no hay rueda durante fines de semana y feriados, por lo que faltan registros dentro de la ventana calendario.

Evidencia: en los resultados LONG de acciones de v1, v2, v3 y v4 se observan cero cierres `TIME_EXIT`; en cripto si existen porque cotiza todos los dias. Tambien permanecen abiertas cientos de senales de acciones en el historial bruto.

Impacto: las operaciones de acciones que no tocaron stop ni objetivo no reciben el cierre temporal esperado. Esto puede alterar el numero de operaciones disponibles, la duracion real y el PnL de la cartera secuencial. Los resultados v1-v4 deben considerarse preliminares hasta resolver este punto.

### M2-H2 - Parametros y ajustes contextuales tienen riesgo de sobreajuste

Severidad: Alta.

Las variantes contextuales se seleccionan con estadisticas calculadas en la misma historia donde se evalua el rendimiento. Existen filtros de muestra, profit factor, PnL p05 y stop loss, pero no hay una separacion formal train/test, walk-forward o periodo final fuera de muestra.

Impacto: una variante puede verse buena por azar en un contexto escaso y luego fallar en produccion. Los requisitos actuales reducen el riesgo, pero no lo eliminan.

### M2-H3 - Earnings y noticias no estan validados historicamente

Severidad: Alta.

El score de earnings y las reglas de noticias son recientes. En el contexto historico, 12.576 de 12.596 registros estan en `NO_EARNINGS_DATA`; noticias solo existen desde julio de 2026.

Impacto: el backtest completo mide principalmente precio, indicadores y macro de mercado. No permite demostrar una mejora historica atribuible a earnings o noticias.

### M2-M1 - Tipo de cambio USD/CLP fijo

Severidad: Media.

El capital se expresa en CLP y los precios en USD, pero las versiones usan `usd_clp_assumption = 950` fijo para todo 2019-2026.

Impacto: el PnL historico en CLP y los tamanos teoricos no incorporan las variaciones reales de USD/CLP. La comparacion relativa entre versiones sigue siendo util, pero el monto absoluto en CLP es aproximado.

### M2-M2 - Orden intradia desconocido dentro de una vela diaria

Severidad: Media.

Con velas diarias, si en una misma fecha el minimo cruza el stop y el maximo cruza un objetivo, no se conoce cual ocurrio primero. La implementacion prioriza stop, que es una convencion conservadora.

Impacto: reduce optimismo artificial, pero no reproduce el orden real de mercado. La validacion fina de entradas y salidas requiere velas intradia reales.

### M2-M3 - Capital secuencial sin sizing plenamente compuesto

Severidad: Media.

La curva diaria suma PnL realizado al capital mostrado, pero el sizing base de las senales parte del capital configurado de $10.000.000 CLP. Por ello la curva es una referencia de PnL acumulado conservadora, no una simulacion completa de reinversion dinamica.

### M2-M4 - Coherencia de frecuencia en documentacion y contexto

Severidad: Baja.

El sistema principal ya usa una sola senal diaria por activo, aunque algunas descripciones historicas aun mencionan bloques de cuatro horas. La logica diaria es consistente; la nomenclatura residual puede confundir futuras auditorias.

## Limites de interpretacion

- La curva principal es LONG secuencial, no una cartera de todas las senales ni una ejecucion real.
- Los resultados de v1-v4 no se suman entre si.
- El mejor PnL no equivale a mejor estrategia sin analizar drawdown, dispersion, periodos negativos y muestra fuera de entrenamiento.
- La estrategia intradia de BTC/ETH es independiente. Actualmente esta en evaluacion y sus resultados iniciales son negativos; no debe promoverse a ejecucion automatica.

## Conclusion M2

La arquitectura tiene controles de riesgo y separa correctamente las cuatro curvas. v2 lidera el PnL acumulado actual, v3 lidera el win rate y v4 es la mas selectiva. Sin embargo, el defecto de salida por tiempo en acciones es material y debe resolverse antes de usar estos resultados para asignar dinero real o declarar una version superior. Luego corresponde validar mediante walk-forward y separar periodos de calibracion de periodos de prueba.

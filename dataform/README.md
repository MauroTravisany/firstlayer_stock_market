# Dataform - Portfolio Valuation

Este proyecto Dataform calcula una clasificacion diaria de la cartera usando:

- precios diarios desde `acciones_dataset.valores_acciones_recientes`
- ratios financieros desde `acciones_dataset.financial_ratios_snapshot`
- ultimos estados financieros desde `acciones_dataset.financial_statements`

## Tabla generada

```text
acciones_dataset.portfolio_valuation_daily
acciones_dataset.portfolio_daily_signal
```

Las tablas quedan particionadas por `analysis_date`.

## Clasificaciones

```text
BARATA        valuation_score >= 2
PRECIO_JUSTO valuation_score >= 0 y < 2
CARA          valuation_score < 0
```

Si no hay datos fundamentales suficientes:

```text
SIN_DATOS_FUNDAMENTALES
```

## Estado de datos financieros

```text
FINANCIERO_AYER       snapshot financiero del dia anterior al precio
FINANCIERO_MISMO_DIA  snapshot financiero del mismo dia
FINANCIERO_REZAGADO   snapshot financiero anterior a ayer
SIN_SNAPSHOT_FINANCIERO
```

## Senal diaria

`portfolio_daily_signal` combina:

- valoracion fundamental
- calidad financiera
- momentum de precio
- riesgo/volatilidad

Senales posibles:

```text
COMPRAR_OBSERVAR
VENDER_OBSERVAR
CALIDAD_ALTA_PRECIO_JUSTO
MANTENER
SOBREVALORADA
TRAMPA_DE_VALOR
RIESGO_ALTO
DATOS_INSUFICIENTES
```

La columna `final_score` ordena las oportunidades diarias de compra. La columna `sell_score` ordena las posibles ventas por sobrevaloracion, deterioro o riesgo.

Senales de venta:

```text
VENTA_CLARA
VENTA_PARCIAL_OBSERVAR
MANTENER_OBSERVAR_VALORACION
SIN_SENAL_VENTA
SIN_DATOS
```

`suggested_sell_price` marca una zona objetiva de revision de venta basada en precio actual, valoracion, momentum y riesgo. No es una orden de venta.

## Paper trading direccional

`trading_directional_signals` toma las senales activas y contrasta dos puntuaciones: una para subida y otra para caida. Ambas consideran tecnica, contexto macro, factores del activo, miedo de mercado, volatilidad y cercania de resultados.

- `LONG`: ventaja al alza clara. Es el unico estado que puede enviarse a Alpaca Paper.
- `SHORT_SIMULATED`: ventaja bajista clara. Se registra y se evalua en el backtest, pero no se envia al broker hasta que acumule evidencia suficiente.
- `NO_TRADE`: no hay ventaja clara o el riesgo es elevado.

`trading_directional_trade_results` mantiene el historial bruto de ambos sentidos, aplicando spread, slippage, stop, objetivos y horizonte de la estrategia.

Para evitar sumar capital ficticio en operaciones incompatibles, el reporte principal usa:

- `trading_directional_strategy_backtest`: selecciona una sola posicion LONG a la vez por estrategia y espera su cierre antes de reutilizar capital.
- `trading_directional_strategy_daily_summary`: curva de capital independiente para v1, v2, v3 y v4. Estas curvas no se suman entre si.
- `trading_directional_daily_summary`: usa v2 solo como referencia diaria compatible con alertas y muestra la comparativa de las cuatro variantes por separado.
- `trading_v5_high_turnover_*`: experimento separado sobre el benchmark G3 y V2. Simula hasta ocho cupos concurrentes, 10% maximo por cupo y salidas temporales de 3 dias para cripto o 5 para acciones. Es solo backtest y no es leido por Alpaca.

Los `SHORT_SIMULATED` quedan como diagnostico historico separado: no llegan a Alpaca Paper y no afectan el PnL principal de los largos.

## Frecuencia y backtesting

El backtest principal usa `trading_price_features`, una serie **diaria homogenea** desde 2019. Si un dia contiene velas de 15 minutos, se consolidan en una unica vela diaria: primera apertura, maximo, minimo, ultimo cierre y volumen acumulado. Asi los retornos, medias moviles y ATR siempre comparan dias con dias.

`trading_intraday_4h_backtest` es una pista independiente para experimentacion intradia. En acciones solo considera sesiones con al menos 12 velas reales de 15 minutos y las agrupa en velas de cuatro horas; para cripto usa las velas reales de cuatro horas que ya entrega la ingesta. No completa huecos ni reutiliza las velas diarias antiguas. Exige 60 sesiones reales por activo antes de publicar resultados, para evitar conclusiones basadas en una muestra demasiado corta.

`trading_intraday_4h_readiness` muestra por activo cuantas sesiones reales existen, cuantas faltan y si el backtest ya esta listo.

No se deben sumar ni comparar como si fueran una misma cartera los resultados diarios y los intradia: tienen horizonte, frecuencia y universo temporal distintos.

## Ejecucion local

Desde `dataform/`:

```bash
npm install
npx dataform compile
npx dataform run
```

En GCP Dataform, conectar este directorio como repositorio y programar la ejecucion despues de los ETL diarios.

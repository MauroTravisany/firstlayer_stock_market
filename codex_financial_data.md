# Propuesta de ETL para informacion financiera y ratios

## Objetivo

El objetivo de este segundo ETL es complementar el pipeline de precios diarios con informacion financiera de las empresas. La idea es dejar de mirar solamente el movimiento de la accion y empezar a entender tambien la salud del negocio detras de cada ticker.

Este ETL deberia funcionar separado del ETL de precios, porque los datos financieros tienen otra frecuencia, otra logica de actualizacion y otro uso de negocio.

## Por que separar esta informacion

Los precios pueden cambiar muchas veces durante el dia. En cambio, los resultados financieros cambian principalmente cuando la empresa publica sus reportes trimestrales o anuales.

Por eso conviene manejar dos tipos de datos:

1. Datos reportados por la empresa.
2. Ratios o metricas de mercado que pueden cambiar con mayor frecuencia.

Esta separacion permite construir alertas mas inteligentes sin mezclar datos diarios de precio con datos contables que no cambian todos los dias.

## Tabla 1: `financial_statements`

Esta tabla guarda la informacion financiera reportada oficialmente por la empresa. Deberia cambiar solo cuando hay una nueva entrega de resultados o cuando la fuente corrige informacion historica.

### Pregunta de negocio que responde

Esta tabla responde:

```text
Como le fue realmente a la empresa durante el periodo reportado?
```

### Campos sugeridos

```text
ticker
fiscal_year
fiscal_quarter
period_end_date
report_date
currency
revenue
gross_profit
operating_income
net_income
eps_basic
eps_diluted
total_assets
total_liabilities
total_debt
shareholders_equity
operating_cash_flow
free_cash_flow
source
loaded_at
```

### Llave recomendada

```text
ticker + fiscal_year + fiscal_quarter
```

Con esta llave, si el ETL vuelve a encontrar el mismo periodo para la misma empresa, deberia hacer `UPDATE` mediante `MERGE`, no insertar una fila duplicada.

### Frecuencia recomendada

```text
1 vez al dia, o 2 a 3 veces por semana.
```

No es necesario ejecutarla muchas veces al dia, porque los estados financieros no cambian a cada minuto.

## Tabla 2: `financial_ratios_snapshot`

Esta tabla guarda ratios y metricas que pueden moverse con mas frecuencia, especialmente cuando dependen del precio de mercado de la accion.

### Pregunta de negocio que responde

Esta tabla responde:

```text
Como se ve valorizada la empresa hoy?
```

### Campos sugeridos

```text
ticker
snapshot_date
price
market_cap
enterprise_value
pe_ratio
forward_pe
price_to_book
price_to_sales
ev_to_ebitda
dividend_yield
beta
roe
roa
profit_margin
gross_margin
operating_margin
debt_to_equity
current_ratio
source
loaded_at
```

### Llave recomendada

```text
ticker + snapshot_date
```

Con esta llave, el ETL puede ejecutarse una vez al dia y actualizar el snapshot del dia si ya existe. Si mas adelante se quiere guardar mas de una observacion diaria, la llave podria evolucionar a:

```text
ticker + snapshot_timestamp
```

### Frecuencia recomendada

```text
1 vez al dia.
```

Esta tabla podria ejecutarse con mas frecuencia que `financial_statements`, pero no parece necesario hacerlo en tiempo real si el negocio apunta a alertas y analisis diarios.

## Relacion con el ETL de precios

El ETL de precios puede seguir ejecutandose dos veces al dia para capturar movimientos relevantes y generar alertas. Este nuevo ETL financiero deberia correr de forma independiente.

Una separacion posible seria:

```text
daily_stock_prices
financial_statements
financial_ratios_snapshot
```

Luego, en BigQuery, se pueden cruzar las tablas por `ticker` y fecha para construir analisis mas completos.

## Ideas de alertas de negocio

Con estas tablas se pueden crear alertas mas utiles que una alerta basada solo en precio.

Ejemplos:

```text
Precio cae fuerte + fundamentos estables = posible oportunidad.
Precio sube mucho + P/E muy alto = posible sobrevaloracion.
Deuda sube + margen cae = alerta de deterioro financiero.
EPS mejora + precio no reacciona = posible oportunidad.
Margen cae varios trimestres seguidos = alerta de perdida de eficiencia.
Free cash flow negativo + deuda alta = alerta de riesgo financiero.
```

## Recomendacion inicial

Para partir, conviene implementar primero una version simple:

```text
1. Crear una funcion ETL separada para datos financieros.
2. Crear la tabla `financial_statements`.
3. Crear la tabla `financial_ratios_snapshot`.
4. Ejecutar `financial_statements` una vez al dia o algunas veces por semana.
5. Ejecutar `financial_ratios_snapshot` una vez al dia.
6. Usar `MERGE` para evitar duplicados.
```

La clave es no mezclar datos reportados con ratios diarios. Asi el proyecto queda preparado para analisis fundamental, alertas y comparaciones historicas sin perder claridad en el modelo de datos.

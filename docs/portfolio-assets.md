# Portfolio Assets

El portafolio maestro vive en BigQuery:

```text
stocks-437902.acciones_dataset.portfolio_assets
```

Los procesos diarios leen todos los registros con:

```sql
enabled = TRUE
```

## Esquema

```text
ticker STRING
asset_name STRING
asset_type STRING
enabled BOOL
notes STRING
created_at TIMESTAMP
updated_at TIMESTAMP
```

## Agregar un ticker

```sql
MERGE `stocks-437902.acciones_dataset.portfolio_assets` T
USING (
  SELECT
    'AMD' AS ticker,
    'Advanced Micro Devices' AS asset_name,
    'stock' AS asset_type,
    TRUE AS enabled,
    '' AS notes
) S
ON T.ticker = S.ticker
WHEN MATCHED THEN UPDATE SET
  asset_name = S.asset_name,
  asset_type = S.asset_type,
  enabled = S.enabled,
  notes = S.notes,
  updated_at = CURRENT_TIMESTAMP()
WHEN NOT MATCHED THEN INSERT (
  ticker, asset_name, asset_type, enabled, notes, created_at, updated_at
) VALUES (
  S.ticker, S.asset_name, S.asset_type, S.enabled, S.notes, CURRENT_TIMESTAMP(), CURRENT_TIMESTAMP()
);
```

## Desactivar un ticker

```sql
UPDATE `stocks-437902.acciones_dataset.portfolio_assets`
SET enabled = FALSE, updated_at = CURRENT_TIMESTAMP()
WHERE ticker = 'AMD';
```

No es necesario cambiar Cloud Scheduler ni redeployar servicios para modificar el portafolio.

## Criptoactivos

Para cripto se usan los tickers de Yahoo Finance con sufijo `-USD`, por ejemplo:

```text
BTC-USD
ETH-USD
```

Estos activos deben quedar con:

```text
asset_type = crypto
```

El sistema no les aplica PE, P/S, EV/EBITDA, ROE ni deuda, porque no son empresas. Se evalúan por precio, tendencia, volatilidad, distancia contra máximos, medias móviles y relación BTC/ETH para detectar dominancia de Bitcoin o posible rotación hacia Ethereum/altcoins.

La carga diaria guarda cripto en velas de 4 horas. Internamente se consulta Yahoo Finance en 1 hora y se consolida a 4 horas para reducir ruido y volumen de datos.

Para cargar historico de BTC/ETH:

```bash
curl -X POST "$STOCKDAILY_URL" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"tickers":["BTC-USD","ETH-USD"],"start_date":"2026-03-01","end_date":"2026-07-24","send_alert":false}'
```

`end_date` es exclusivo: si quieres incluir el 23 de julio, usa `2026-07-24`.

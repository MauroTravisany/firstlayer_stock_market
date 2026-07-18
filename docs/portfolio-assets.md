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

# Proveedor de Google Cloud
provider "google" {
  project = var.project_id     # El ID de tu proyecto en Google Cloud
  region  = var.region         # La región donde se alojarán los recursos
}


# Crear el dataset en BigQuery
resource "google_bigquery_dataset" "acciones_dataset" {
  dataset_id = var.dataset_id  # Nombre del dataset
  location   = var.region      # La región donde estará el dataset
}

# Tabla de datos recientes (último año)
resource "google_bigquery_table" "tabla_recientes" {
  dataset_id = google_bigquery_dataset.acciones_dataset.dataset_id
  table_id   = var.tabla_recientes
  deletion_protection = false
  schema = <<EOF
  [
    {
      "name": "id",
      "type": "BYTES",
      "mode": "REQUIRED"
    },
    {
      "name": "fecha",
      "type": "DATE",
      "mode": "REQUIRED"
    },
    {
      "name": "hora",
      "type": "TIME",
      "mode": "REQUIRED"
    },
    {
      "name": "ticker",
      "type": "STRING",
      "mode": "REQUIRED"
    },
    {
      "name": "open",
      "type": "FLOAT",
      "mode": "NULLABLE"
    },
    {
      "name": "close",
      "type": "FLOAT",
      "mode": "NULLABLE"
    },
    {
      "name": "high",
      "type": "FLOAT",
      "mode": "NULLABLE"
    },
    {
      "name": "low",
      "type": "FLOAT",
      "mode": "NULLABLE"
    },
    {
      "name": "valor_promedio",
      "type": "FLOAT",
      "mode": "NULLABLE"
    },
    {
      "name": "volumen",
      "type": "INTEGER",
      "mode": "NULLABLE"
    },
    {
      "name": "pct_change",
      "type": "FLOAT",
      "mode": "NULLABLE"
    },
    {
      "name": "volatilidad",
      "type": "FLOAT",
      "mode": "NULLABLE"
    },
    {
      "name": "fecha_creacion",  
      "type": "TIMESTAMP",
      "mode": "REQUIRED"
    }
  ]
  EOF

  time_partitioning {
    type  = "DAY"
    field = "fecha"
  }

  # Definir clustering como argumento
  clustering = ["ticker"]
}

# Tabla de datos históricos
resource "google_bigquery_table" "tabla_historica" {
  dataset_id = google_bigquery_dataset.acciones_dataset.dataset_id
  table_id   = var.tabla_historica
  deletion_protection = false
  schema = <<EOF
  [
    {
      "name": "id",
      "type": "BYTES",
      "mode": "REQUIRED"
    },
    {
      "name": "fecha",
      "type": "DATE",
      "mode": "REQUIRED"
    },
    {
      "name": "hora",
      "type": "TIME",
      "mode": "REQUIRED"
    },
    {
      "name": "ticker",
      "type": "STRING",
      "mode": "REQUIRED"
    },
    {
      "name": "open",
      "type": "FLOAT",
      "mode": "NULLABLE"
    },
    {
      "name": "close",
      "type": "FLOAT",
      "mode": "NULLABLE"
    },
    {
      "name": "high",
      "type": "FLOAT",
      "mode": "NULLABLE"
    },
    {
      "name": "low",
      "type": "FLOAT",
      "mode": "NULLABLE"
    },
    {
      "name": "valor_promedio",
      "type": "FLOAT",
      "mode": "NULLABLE"
    },
    {
      "name": "volumen",
      "type": "INTEGER",
      "mode": "NULLABLE"
    },
    {
      "name": "pct_change",
      "type": "FLOAT",
      "mode": "NULLABLE"
    },
    {
      "name": "volatilidad",
      "type": "FLOAT",
      "mode": "NULLABLE"
    }
    ,
    {
      "name": "fecha_creacion",  
      "type": "TIMESTAMP",
      "mode": "REQUIRED"
    }
  ]
  EOF

  time_partitioning {
    type  = "DAY"
    field = "fecha"
  }

  # Definir clustering como argumento con múltiples campos
  clustering = ["ticker", "fecha", "volumen"]
}


# Tabla de indicadores diarios (SMA, RSI)
resource "google_bigquery_table" "tabla_indicadores_diarios" {
  dataset_id = google_bigquery_dataset.acciones_dataset.dataset_id
  table_id   = "indicadores_acciones_diarios"
  deletion_protection = false
  schema = <<EOF
  [
    {
      "name": "id",
      "type": "BYTES",
      "mode": "REQUIRED"
    },
    {
      "name": "fecha",
      "type": "DATE",
      "mode": "REQUIRED"
    },
    {
      "name": "ticker",
      "type": "STRING",
      "mode": "REQUIRED"
    },
    {
      "name": "sma",
      "type": "FLOAT",
      "mode": "NULLABLE"
    },
    {
      "name": "rsi",
      "type": "FLOAT",
      "mode": "NULLABLE"
    },
    {
      "name": "fecha_creacion",  
      "type": "TIMESTAMP",
      "mode": "REQUIRED"
    }
  ]
  EOF

  time_partitioning {
    type  = "DAY"
    field = "fecha"
  }

  
  clustering = ["ticker", "fecha"]
  
}

resource "google_bigquery_table" "financial_statements" {
  dataset_id          = google_bigquery_dataset.acciones_dataset.dataset_id
  table_id            = "financial_statements"
  deletion_protection = false
  schema = <<EOF
  [
    {"name": "ticker", "type": "STRING", "mode": "REQUIRED"},
    {"name": "fiscal_year", "type": "INTEGER", "mode": "REQUIRED"},
    {"name": "fiscal_quarter", "type": "INTEGER", "mode": "REQUIRED"},
    {"name": "period_end_date", "type": "DATE", "mode": "REQUIRED"},
    {"name": "report_date", "type": "DATE", "mode": "NULLABLE"},
    {"name": "currency", "type": "STRING", "mode": "NULLABLE"},
    {"name": "revenue", "type": "FLOAT", "mode": "NULLABLE"},
    {"name": "gross_profit", "type": "FLOAT", "mode": "NULLABLE"},
    {"name": "operating_income", "type": "FLOAT", "mode": "NULLABLE"},
    {"name": "net_income", "type": "FLOAT", "mode": "NULLABLE"},
    {"name": "eps_basic", "type": "FLOAT", "mode": "NULLABLE"},
    {"name": "eps_diluted", "type": "FLOAT", "mode": "NULLABLE"},
    {"name": "total_assets", "type": "FLOAT", "mode": "NULLABLE"},
    {"name": "total_liabilities", "type": "FLOAT", "mode": "NULLABLE"},
    {"name": "total_debt", "type": "FLOAT", "mode": "NULLABLE"},
    {"name": "shareholders_equity", "type": "FLOAT", "mode": "NULLABLE"},
    {"name": "operating_cash_flow", "type": "FLOAT", "mode": "NULLABLE"},
    {"name": "free_cash_flow", "type": "FLOAT", "mode": "NULLABLE"},
    {"name": "source", "type": "STRING", "mode": "NULLABLE"},
    {"name": "loaded_at", "type": "TIMESTAMP", "mode": "REQUIRED"}
  ]
  EOF

  time_partitioning {
    type  = "DAY"
    field = "period_end_date"
  }

  clustering = ["ticker", "fiscal_year", "fiscal_quarter"]
}

resource "google_bigquery_table" "financial_ratios_snapshot" {
  dataset_id          = google_bigquery_dataset.acciones_dataset.dataset_id
  table_id            = "financial_ratios_snapshot"
  deletion_protection = false
  schema = <<EOF
  [
    {"name": "ticker", "type": "STRING", "mode": "REQUIRED"},
    {"name": "snapshot_date", "type": "DATE", "mode": "REQUIRED"},
    {"name": "price", "type": "FLOAT", "mode": "NULLABLE"},
    {"name": "market_cap", "type": "FLOAT", "mode": "NULLABLE"},
    {"name": "enterprise_value", "type": "FLOAT", "mode": "NULLABLE"},
    {"name": "pe_ratio", "type": "FLOAT", "mode": "NULLABLE"},
    {"name": "forward_pe", "type": "FLOAT", "mode": "NULLABLE"},
    {"name": "price_to_book", "type": "FLOAT", "mode": "NULLABLE"},
    {"name": "price_to_sales", "type": "FLOAT", "mode": "NULLABLE"},
    {"name": "ev_to_ebitda", "type": "FLOAT", "mode": "NULLABLE"},
    {"name": "dividend_yield", "type": "FLOAT", "mode": "NULLABLE"},
    {"name": "beta", "type": "FLOAT", "mode": "NULLABLE"},
    {"name": "roe", "type": "FLOAT", "mode": "NULLABLE"},
    {"name": "roa", "type": "FLOAT", "mode": "NULLABLE"},
    {"name": "profit_margin", "type": "FLOAT", "mode": "NULLABLE"},
    {"name": "gross_margin", "type": "FLOAT", "mode": "NULLABLE"},
    {"name": "operating_margin", "type": "FLOAT", "mode": "NULLABLE"},
    {"name": "debt_to_equity", "type": "FLOAT", "mode": "NULLABLE"},
    {"name": "current_ratio", "type": "FLOAT", "mode": "NULLABLE"},
    {"name": "source", "type": "STRING", "mode": "NULLABLE"},
    {"name": "loaded_at", "type": "TIMESTAMP", "mode": "REQUIRED"}
  ]
  EOF

  time_partitioning {
    type  = "DAY"
    field = "snapshot_date"
  }

  clustering = ["ticker"]
}

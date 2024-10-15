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
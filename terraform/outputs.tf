output "dataset_name" {
  description = "Nombre del dataset creado en BigQuery"
  value       = google_bigquery_dataset.acciones_dataset.dataset_id
}

output "tabla_recientes_name" {
  description = "Nombre de la tabla de datos recientes"
  value       = google_bigquery_table.tabla_recientes.table_id
}

output "tabla_historica_name" {
  description = "Nombre de la tabla de datos históricos"
  value       = google_bigquery_table.tabla_historica.table_id
}

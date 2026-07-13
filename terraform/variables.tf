variable "project_id" {
  description = "El ID de tu proyecto en Google Cloud"
  type        = string
  default     = "stocks-437902"
}

variable "region" {
  description = "La región de Google Cloud donde se alojarán los recursos"
  type        = string
  default     = "us-east1"  # Cambia por la región que prefieras (ej: southamerica-east1)
}

variable "dataset_id" {
  description = "El nombre del dataset donde se almacenarán las tablas"
  type        = string
  default     = "acciones_dataset"
}

variable "tabla_recientes" {
  description = "Nombre de la tabla de datos recientes (último año)"
  type        = string
  default     = "valores_acciones_recientes"
}

variable "tabla_historica" {
  description = "Nombre de la tabla de datos históricos"
  type        = string
  default     = "valores_acciones_historicas"
}

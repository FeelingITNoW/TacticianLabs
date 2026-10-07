variable "project_id" {
  type        = string
  description = "GCP project that hosts the ingest job."
}

variable "region" {
  type        = string
  default     = "us-central1"
  description = "Region for Cloud Run, Artifact Registry, Cloud Build and Scheduler. Must match the Developer Connect connection's region."
}

variable "git_repository_link" {
  type        = string
  description = "Developer Connect repo link, e.g. projects/<p>/locations/<region>/connections/<conn>/gitRepositoryLinks/<link>. Created once in the console (see README)."
}

variable "bigquery_dataset" {
  type        = string
  default     = "tft"
  description = "Dataset holding the match tables. A \"<name>_staging\" dataset is created next to it."
}

variable "schedule" {
  type        = string
  default     = "0 6 * * *"
  description = "Cron (UTC) for the daily ingest run."
}

variable "skip_embeddings" {
  type        = bool
  default     = true
  description = "Skip the per-board Gemini embedding at ingest (participants.embedding stays empty). Nothing reads the embeddings yet, and `python -m jobs.load_gcs_matches --reload` backfills them from the GCS archive. Set false to embed again."
}

variable "cluster_schedule" {
  type        = string
  default     = "0 15 * * *"
  description = "Cron (UTC) for the daily composition clustering, which should start after the ingest has finished (06:00 plus its 8 hour timeout, plus an hour of margin)."
}

variable "developer_connect_region" {
  type        = string
  default     = null
  description = "Region of the Developer Connect connection (from its gitRepositoryLinks resource name). The Cloud Build trigger must live in this same region; it can differ from var.region, which governs Cloud Run/Artifact Registry/Scheduler. Defaults to var.region."
}

variable "gcs_bucket_name" {
  type        = string
  default     = null
  description = "Bucket for raw match JSON. GCS names are globally unique, so the default is \"<project_id>-tft-match-data\"; set this if that's taken."
}

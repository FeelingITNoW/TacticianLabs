output "job_name" {
  value = google_cloud_run_v2_job.ingest.name
}

output "cluster_job_name" {
  value = google_cloud_run_v2_job.cluster_compositions.name
}

output "image_repository" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.tft.repository_id}/ingest"
}

output "secret_ids" {
  description = "Add a value to each with: printf '%s' \"$VALUE\" | gcloud secrets versions add <id> --data-file=-"
  value       = [for s in google_secret_manager_secret.job : s.secret_id]
}

output "gcs_bucket" {
  value = google_storage_bucket.tft_match_data.name
}

output "bigquery_dataset" {
  value = google_bigquery_dataset.tft.dataset_id
}

output "ask_logs_bucket" {
  description = "Set as ASK_LOG_BUCKET on the agent service."
  value       = google_storage_bucket.ask_logs.name
}

output "ask_agent_service_account" {
  description = "Create a key for it and set that as the agent's GOOGLE_CREDENTIALS_JSON."
  value       = google_service_account.ask_agent.email
}

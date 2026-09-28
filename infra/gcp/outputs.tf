output "job_name" {
  value = google_cloud_run_v2_job.ingest.name
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

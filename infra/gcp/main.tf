locals {
  job_name = "tft-ingest"

  # GCS bucket names are globally unique across all of GCP, so default to
  # something project-scoped unless the caller picks their own.
  gcs_bucket_name = coalesce(var.gcs_bucket_name, "${var.project_id}-tft-match-data")

  # The Cloud Build trigger must sit in the same region as the Developer
  # Connect connection referenced by git_repository_link, which need not be
  # var.region (Cloud Run/Artifact Registry/Scheduler's region).
  developer_connect_region = coalesce(var.developer_connect_region, var.region)

  # Env var name the job reads -> Secret Manager secret id.
  # Values are added out of band (gcloud secrets versions add) so they never land in tfstate.
  secret_env = {
    supabase_key   = "supabase-key"
    GEMINI_API_KEY = "gemini-api-key"
    RIOT_API_KEY   = "riot-api-key"
  }
}

resource "google_project_service" "apis" {
  for_each = toset([
    "artifactregistry.googleapis.com",
    "cloudbuild.googleapis.com",
    "cloudscheduler.googleapis.com",
    "developerconnect.googleapis.com",
    "run.googleapis.com",
    "secretmanager.googleapis.com",
    "storage.googleapis.com",
  ])
  service            = each.value
  disable_on_destroy = false
}

# --- Match archive (replaces the Backblaze B2 bucket in the repo-root main.tf) ---

resource "google_storage_bucket" "tft_match_data" {
  name                        = local.gcs_bucket_name
  location                    = var.region
  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  force_destroy               = false

  depends_on = [google_project_service.apis]
}

# --- Artifact Registry ------------------------------------------------------

resource "google_artifact_registry_repository" "tft" {
  repository_id = "tft"
  location      = var.region
  format        = "DOCKER"

  # Keep the 5 newest images; stays under the 0.5 GB free tier.
  cleanup_policy_dry_run = false
  cleanup_policies {
    id     = "keep-recent"
    action = "KEEP"
    most_recent_versions {
      keep_count = 5
    }
  }
  cleanup_policies {
    id     = "delete-rest"
    action = "DELETE"
    condition {
      tag_state = "ANY"
    }
  }

  depends_on = [google_project_service.apis]
}

# --- Secrets ----------------------------------------------------------------

resource "google_secret_manager_secret" "job" {
  for_each  = local.secret_env
  secret_id = each.value
  replication {
    auto {}
  }
  depends_on = [google_project_service.apis]
}

# --- Service accounts -------------------------------------------------------

resource "google_service_account" "runner" {
  account_id   = "tft-ingest-runner"
  display_name = "TFT ingest Cloud Run Job"
}

resource "google_service_account" "builder" {
  account_id   = "tft-ingest-builder"
  display_name = "TFT ingest Cloud Build"
}

resource "google_service_account" "scheduler" {
  account_id   = "tft-ingest-scheduler"
  display_name = "TFT ingest Cloud Scheduler"
}

resource "google_secret_manager_secret_iam_member" "runner_access" {
  for_each  = google_secret_manager_secret.job
  secret_id = each.value.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runner.email}"
}

resource "google_storage_bucket_iam_member" "runner_bucket_access" {
  bucket = google_storage_bucket.tft_match_data.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.runner.email}"
}

resource "google_artifact_registry_repository_iam_member" "builder_push" {
  repository = google_artifact_registry_repository.tft.name
  location   = var.region
  role       = "roles/artifactregistry.writer"
  member     = "serviceAccount:${google_service_account.builder.email}"
}

resource "google_project_iam_member" "builder" {
  for_each = toset([
    "roles/run.developer", # gcloud run jobs update
    "roles/logging.logWriter",
    "roles/developerconnect.readTokenAccessor", # fetch a GitHub token to clone via the Developer Connect trigger
  ])
  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.builder.email}"
}

# The builder redeploys a job that runs as the runner SA, so it must be able to act as it.
resource "google_service_account_iam_member" "builder_acts_as_runner" {
  service_account_id = google_service_account.runner.name
  role               = "roles/iam.serviceAccountUser"
  member             = "serviceAccount:${google_service_account.builder.email}"
}

# --- Cloud Run Job ----------------------------------------------------------

resource "google_cloud_run_v2_job" "ingest" {
  name                = local.job_name
  location            = var.region
  deletion_protection = false

  template {
    # One task per routing region (AMERICAS, ASIA, EUROPE, SEA); see include/jobs/ingest_matches.py
    task_count  = 4
    parallelism = 4

    template {
      service_account = google_service_account.runner.email
      timeout         = "10800s"
      max_retries     = 1

      containers {
        # Placeholder until the first Cloud Build run; cloudbuild.yaml owns the image after that.
        image = "us-docker.pkg.dev/cloudrun/container/job:latest"

        resources {
          limits = {
            cpu    = "1"
            memory = "1Gi"
          }
        }

        env {
          name  = "supabase_url"
          value = var.supabase_url
        }

        env {
          name  = "GCS_BUCKET"
          value = google_storage_bucket.tft_match_data.name
        }

        dynamic "env" {
          for_each = local.secret_env
          content {
            name = env.key
            value_source {
              secret_key_ref {
                secret  = google_secret_manager_secret.job[env.key].secret_id
                version = "latest"
              }
            }
          }
        }
      }
    }
  }

  lifecycle {
    ignore_changes = [
      template[0].template[0].containers[0].image,
      client,
      client_version,
    ]
  }

  depends_on = [
    google_secret_manager_secret_iam_member.runner_access,
    google_storage_bucket_iam_member.runner_bucket_access,
  ]
}

# --- Daily schedule ---------------------------------------------------------

resource "google_cloud_run_v2_job_iam_member" "scheduler_invoker" {
  name     = google_cloud_run_v2_job.ingest.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "serviceAccount:${google_service_account.scheduler.email}"
}

resource "google_cloud_scheduler_job" "daily" {
  name      = "${local.job_name}-daily"
  region    = var.region
  schedule  = var.schedule
  time_zone = "Etc/UTC"

  http_target {
    http_method = "POST"
    uri         = "https://run.googleapis.com/v2/projects/${var.project_id}/locations/${var.region}/jobs/${google_cloud_run_v2_job.ingest.name}:run"
    oauth_token {
      service_account_email = google_service_account.scheduler.email
    }
  }

  depends_on = [google_cloud_run_v2_job_iam_member.scheduler_invoker]
}

# --- Continuous deploy via Developer Connect ---------------------------------

resource "google_cloudbuild_trigger" "ingest" {
  name            = "${local.job_name}-deploy"
  location        = local.developer_connect_region
  service_account = google_service_account.builder.id
  filename        = "cloudbuild.yaml"

  included_files = [
    "include/**",
    "Dockerfile.jobs",
    "requirements-jobs.txt",
    "cloudbuild.yaml",
  ]

  developer_connect_event_config {
    git_repository_link = var.git_repository_link
    push {
      branch = "^main$"
    }
  }

  substitutions = {
    _REGION = var.region
    _JOB    = google_cloud_run_v2_job.ingest.name
  }

  depends_on = [
    google_artifact_registry_repository_iam_member.builder_push,
    google_project_iam_member.builder,
    google_service_account_iam_member.builder_acts_as_runner,
  ]
}

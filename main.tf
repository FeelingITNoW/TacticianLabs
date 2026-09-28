# DEPRECATED: ingestion now uploads to GCS (see infra/gcp/main.tf,
# google_storage_bucket.tft_match_data) instead of this Backblaze B2 bucket.
#
# This file is kept only so `terraform destroy` still has the provider config
# needed to tear down the real B2 bucket + key it created. To finish the move:
#   1. terraform destroy   (uses the state already on disk; deletes the B2
#                            bucket and the tft-ingest-service-key)
#   2. rm main.tf terraform.tfstate terraform.tfstate.backup .terraform.lock.hcl
#      (all already gitignored except main.tf, which is still tracked)
# Do this once you've confirmed the GCS bucket in infra/gcp is receiving data.
terraform {
    required_providers {
        b2 = {
            source  = "Backblaze/b2"
            version = "0.12.1"
        }
    }
}


variable "B2_APPLICATION_KEY_ID" {
    description = "The application key ID for the B2 provider"
    type        = string
    sensitive = true
}

variable "B2_APPLICATION_KEY" {
    description = "The application key for the B2 provider"
    type        = string
    sensitive = true
}

provider "b2" {
    application_key_id = var.B2_APPLICATION_KEY_ID
    application_key = var.B2_APPLICATION_KEY
}

resource "b2_bucket" "tft_bronze" {
    bucket_name = "tft-match-data"
    bucket_type = "allPrivate"
}

resource "b2_application_key" "python_ingest_key" {
    key_name = "tft-ingest-service-key"
    capabilities = [
        "listBuckets",
        "readFiles",
        "writeFiles",
        "deleteFiles",
        "listFiles"
    ]
    bucket_ids = [b2_bucket.tft_bronze.bucket_id]
}

output "ingest_key_id" {
    value = b2_application_key.python_ingest_key.application_key_id
}

output "ingest_application_key" {
    value = b2_application_key.python_ingest_key.application_key
    sensitive = true
}
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
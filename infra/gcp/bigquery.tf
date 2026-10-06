# --- BigQuery: the relational store for parsed matches and stats --------------
#
# Column layouts live in bigquery/<table>.json. BigQuery records primary and
# foreign keys but never enforces them (NOT ENFORCED); the writers in
# include/db/ keep them true. The provider only takes single-column foreign
# keys, so composite links are noted in each table's description instead.
#
# Every per-match table carries played_at and is partitioned on it by day, so
# date-bounded queries and the ingest's delete-then-insert only touch the days
# involved.

locals {
  # Tables nothing else depends on. Created first so the foreign keys below can name them.
  bq_base_tables = {
    players = {
      description     = "One row per Riot account (puuid)."
      primary_key     = ["puuid"]
      partition_field = null
      clustering      = null
    }
    matches = {
      description     = "One row per ranked match."
      primary_key     = ["match_id"]
      partition_field = "played_at"
      clustering      = ["match_id"]
    }
    patch_totals = {
      description     = "Cumulative per-patch match and board counts, the denominators for the stats views."
      primary_key     = ["patch"]
      partition_field = null
      clustering      = null
    }
    champions = {
      description     = "Set reference data from tft-champion.json, keyed by Riot api name."
      primary_key     = ["api_name"]
      partition_field = null
      clustering      = null
    }
    traits = {
      description     = "Set reference data from tft-trait.json, keyed by Riot api name."
      primary_key     = ["api_name"]
      partition_field = null
      clustering      = null
    }
    items = {
      description     = "Reference data from tft-item.json, keyed by Riot api name."
      primary_key     = ["api_name"]
      partition_field = null
      clustering      = null
    }
  }

  bq_linked_tables = {
    player_ranked_stats = {
      description     = "Current ranked snapshot per player from the apex league lists."
      primary_key     = ["puuid"]
      partition_field = null
      clustering      = null
      foreign_keys    = [{ column = "puuid", table = "players", references = "puuid" }]
    }
    participants = {
      description     = "One row per player per match (8 per match): the players <-> matches junction."
      primary_key     = ["match_id", "puuid"]
      partition_field = "played_at"
      clustering      = ["match_id", "puuid"]
      foreign_keys = [
        { column = "match_id", table = "matches", references = "match_id" },
        { column = "puuid", table = "players", references = "puuid" },
      ]
    }
    participant_traits = {
      description     = "Traits on a participant's final board. (match_id, puuid) references participants."
      primary_key     = ["match_id", "puuid", "trait"]
      partition_field = "played_at"
      clustering      = ["trait", "match_id"]
      foreign_keys = [
        { column = "match_id", table = "matches", references = "match_id" },
        { column = "trait", table = "traits", references = "api_name" },
      ]
    }
    participant_units = {
      description     = "Units on a participant's final board, one row per copy. (match_id, puuid) references participants."
      primary_key     = ["match_id", "puuid", "slot"]
      partition_field = "played_at"
      clustering      = ["champion", "match_id"]
      foreign_keys = [
        { column = "match_id", table = "matches", references = "match_id" },
        { column = "champion", table = "champions", references = "api_name" },
      ]
    }
    unit_items = {
      description     = "Items held by a unit. (match_id, puuid, slot) references participant_units."
      primary_key     = ["match_id", "puuid", "slot", "item_index"]
      partition_field = "played_at"
      clustering      = ["item", "match_id"]
      foreign_keys = [
        { column = "match_id", table = "matches", references = "match_id" },
        { column = "item", table = "items", references = "api_name" },
      ]
    }
    champion_totals = {
      description     = "Cumulative per-patch counters per champion, added to by every ingest write (include/data_aggregation). Read through the champion_stats view."
      primary_key     = ["patch", "api_name"]
      partition_field = null
      clustering      = null
      foreign_keys    = [{ column = "api_name", table = "champions", references = "api_name" }]
    }
    trait_totals = {
      description     = "Cumulative per-patch counters per active trait. Read through the trait_stats view."
      primary_key     = ["patch", "api_name"]
      partition_field = null
      clustering      = null
      foreign_keys    = [{ column = "api_name", table = "traits", references = "api_name" }]
    }
    item_totals = {
      description     = "Cumulative per-patch counters per item. Read through the item_stats view."
      primary_key     = ["patch", "api_name"]
      partition_field = null
      clustering      = null
      foreign_keys    = [{ column = "api_name", table = "items", references = "api_name" }]
    }
    champion_item_totals = {
      description     = "Cumulative per-patch counters per champion + item combo. Read through the champion_item_stats view."
      primary_key     = ["patch", "champion", "item"]
      partition_field = null
      clustering      = null
      foreign_keys = [
        { column = "champion", table = "champions", references = "api_name" },
        { column = "item", table = "items", references = "api_name" },
      ]
    }
  }

  # Views over the totals tables. Rates are derived here from exact integer
  # counters, so nothing stored is ever rounded. Templates live in bigquery/views/.
  bq_stats_views = {
    champion_stats = {
      file        = "entity_stats.sql.tftpl"
      vars        = { totals = "champion_totals" }
      description = "Per-patch champion stats derived from champion_totals."
    }
    trait_stats = {
      file        = "entity_stats.sql.tftpl"
      vars        = { totals = "trait_totals" }
      description = "Per-patch stats for active traits derived from trait_totals."
    }
    item_stats = {
      file        = "entity_stats.sql.tftpl"
      vars        = { totals = "item_totals" }
      description = "Per-patch item stats derived from item_totals."
    }
    champion_item_stats = {
      file        = "champion_item_stats.sql.tftpl"
      vars        = {}
      description = "Per-patch stats for each champion + item combo derived from champion_item_totals."
    }
  }

  # What dashboards and LLM queries read: the latest patch only, with display names.
  bq_current_views = {
    current_champion_stats = {
      file        = "current_champion_stats.sql.tftpl"
      description = "champion_stats for the latest patch, with names and costs."
    }
    current_trait_stats = {
      file        = "current_trait_stats.sql.tftpl"
      description = "trait_stats for the latest patch, with names."
    }
    current_item_stats = {
      file        = "current_item_stats.sql.tftpl"
      description = "item_stats for the latest patch, with names."
    }
    current_champion_item_stats = {
      file        = "current_champion_item_stats.sql.tftpl"
      description = "champion_item_stats for the latest patch, with names."
    }
  }
}

resource "google_bigquery_dataset" "tft" {
  dataset_id  = var.bigquery_dataset
  location    = var.region
  description = "TFT matches, players, reference data and stats."

  depends_on = [google_project_service.apis]
}

# Writers load rows here with free load jobs, then copy them into the real
# tables with one SQL script. Tables expire after a day, so a crash can't leak them.
resource "google_bigquery_dataset" "tft_staging" {
  dataset_id                  = "${var.bigquery_dataset}_staging"
  location                    = var.region
  description                 = "Short-lived load targets for include/db/bq.py."
  default_table_expiration_ms = 24 * 60 * 60 * 1000

  depends_on = [google_project_service.apis]
}

resource "google_bigquery_table" "base" {
  for_each    = local.bq_base_tables
  dataset_id  = google_bigquery_dataset.tft.dataset_id
  table_id    = each.key
  description = each.value.description
  schema      = file("${path.module}/bigquery/${each.key}.json")
  clustering  = each.value.clustering

  dynamic "time_partitioning" {
    for_each = each.value.partition_field == null ? [] : [each.value.partition_field]
    content {
      type  = "DAY"
      field = time_partitioning.value
    }
  }

  table_constraints {
    primary_key {
      columns = each.value.primary_key
    }
  }
}

resource "google_bigquery_table" "linked" {
  for_each    = local.bq_linked_tables
  dataset_id  = google_bigquery_dataset.tft.dataset_id
  table_id    = each.key
  description = each.value.description
  schema      = file("${path.module}/bigquery/${each.key}.json")
  clustering  = each.value.clustering

  dynamic "time_partitioning" {
    for_each = each.value.partition_field == null ? [] : [each.value.partition_field]
    content {
      type  = "DAY"
      field = time_partitioning.value
    }
  }

  table_constraints {
    primary_key {
      columns = each.value.primary_key
    }

    dynamic "foreign_keys" {
      for_each = each.value.foreign_keys
      content {
        name = "${each.key}_${foreign_keys.value.column}_fkey"
        referenced_table {
          project_id = var.project_id
          dataset_id = google_bigquery_dataset.tft.dataset_id
          table_id   = google_bigquery_table.base[foreign_keys.value.table].table_id
        }
        column_references {
          referencing_column = foreign_keys.value.column
          referenced_column  = foreign_keys.value.references
        }
      }
    }
  }
}

resource "google_bigquery_table" "stats_views" {
  for_each            = local.bq_stats_views
  dataset_id          = google_bigquery_dataset.tft.dataset_id
  table_id            = each.key
  description         = each.value.description
  deletion_protection = false

  view {
    use_legacy_sql = false
    query = templatefile("${path.module}/bigquery/views/${each.value.file}", merge(
      { project = var.project_id, dataset = google_bigquery_dataset.tft.dataset_id },
      each.value.vars,
    ))
  }

  depends_on = [google_bigquery_table.base, google_bigquery_table.linked]
}

# BigQuery validates a view's SQL when it is created, so these wait for the
# stats views they select from.
resource "google_bigquery_table" "current_views" {
  for_each            = local.bq_current_views
  dataset_id          = google_bigquery_dataset.tft.dataset_id
  table_id            = each.key
  description         = each.value.description
  deletion_protection = false

  view {
    use_legacy_sql = false
    query = templatefile("${path.module}/bigquery/views/${each.value.file}", {
      project = var.project_id
      dataset = google_bigquery_dataset.tft.dataset_id
    })
  }

  depends_on = [google_bigquery_table.stats_views]
}

# --- Access for the ingest job ----------------------------------------------

resource "google_project_iam_member" "runner_bigquery_jobs" {
  project = var.project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.runner.email}"
}

resource "google_bigquery_dataset_iam_member" "runner_editor" {
  for_each = {
    tft     = google_bigquery_dataset.tft.dataset_id
    staging = google_bigquery_dataset.tft_staging.dataset_id
  }
  dataset_id = each.value
  role       = "roles/bigquery.dataEditor"
  member     = "serviceAccount:${google_service_account.runner.email}"
}

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
      description     = "One row per recorded match: ranked games (queue_id 1100) from any crawled tier, plus normal games (1090) from Challengers. Stats and comps count ranked only."
      primary_key     = ["match_id"]
      partition_field = "played_at"
      clustering      = ["match_id"]
    }
    rejected_matches = {
      description     = "Fetched matches the ingest chose not to record (a mode we never keep, or a normal game no Challenger played). Checked before fetching so each is requested once."
      primary_key     = ["match_id"]
      partition_field = "played_at"
      clustering      = ["match_id"]
    }
    patch_totals = {
      description     = "Cumulative per-patch match, board and result counts (placement sum, top 4s, wins), the denominators for the stats views and the baseline for their without-the-entity deltas."
      primary_key     = ["patch"]
      partition_field = null
      clustering      = null
    }
    compositions = {
      description     = "Per-patch comps found by clustering board vectors (include/data_aggregation/compositions.py), with exact counters over every assigned board. Read through the composition_stats view."
      primary_key     = ["patch", "comp_id"]
      partition_field = null
      clustering      = null
    }
    composition_variants = {
      description     = "Per-patch variants of each comp: sub-clusters that differ from it by a few units or traits, with exact counters over their assigned boards. Read through the composition_variant_stats view."
      primary_key     = ["patch", "variant_id"]
      partition_field = null
      clustering      = null
    }
    composition_star_totals = {
      description     = "Per-patch counters of each comp's boards by each unit's star level, rebuilt by the clustering job with the comps (include/data_aggregation). Read through the composition_star_upgrade_stats view."
      primary_key     = ["patch", "comp_id", "champion", "star"]
      partition_field = null
      clustering      = null
    }
    composition_completed_item_totals = {
      description     = "Per-patch counters of each comp's boards by completed items held, rebuilt by the clustering job with the comps. Read through the composition_completed_item_stats view."
      primary_key     = ["patch", "comp_id", "completed_items"]
      partition_field = null
      clustering      = null
    }
    composition_board_cost_totals = {
      description     = "Per-patch counters of each comp's boards by board cost, rebuilt by the clustering job with the comps. Read through the composition_board_cost_stats view."
      primary_key     = ["patch", "comp_id", "board_cost"]
      partition_field = null
      clustering      = null
    }
    composition_trait_totals = {
      description     = "Per-patch counters of each comp's boards by each active trait and its tier, rebuilt by the clustering job with the comps. Read through the composition_trait_stats view."
      primary_key     = ["patch", "comp_id", "trait", "tier"]
      partition_field = null
      clustering      = null
    }
    champions = {
      description     = "Set reference data from include/db/reference_data/tft-champion.json, keyed by Riot api name."
      primary_key     = ["api_name"]
      partition_field = null
      clustering      = null
    }
    traits = {
      description     = "Set reference data from include/db/reference_data/tft-trait.json, keyed by Riot api name."
      primary_key     = ["api_name"]
      partition_field = null
      clustering      = null
    }
    items = {
      description     = "Reference data from include/db/reference_data/tft-item.json, keyed by Riot api name."
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
    participant_compositions = {
      description     = "The comp each board was assigned to; boards that fit no comp have no row. (patch, comp_id) references compositions, (match_id, puuid) references participants."
      primary_key     = ["match_id", "puuid"]
      partition_field = "played_at"
      clustering      = ["patch", "comp_id"]
      foreign_keys    = [{ column = "match_id", table = "matches", references = "match_id" }]
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
    champion_item_pair_totals = {
      description     = "Cumulative per-patch counters per champion + item pair (two items on the same unit, item_a <= item_b). Read through the champion_item_pair_stats view."
      primary_key     = ["patch", "champion", "item_a", "item_b"]
      partition_field = null
      clustering      = null
      foreign_keys = [
        { column = "champion", table = "champions", references = "api_name" },
        { column = "item_a", table = "items", references = "api_name" },
        { column = "item_b", table = "items", references = "api_name" },
      ]
    }
    champion_item_trio_totals = {
      description     = "Cumulative per-patch counters per champion + full 3-item build (a unit holding exactly those items, item_a <= item_b <= item_c). Read through the champion_item_trio_stats view."
      primary_key     = ["patch", "champion", "item_a", "item_b", "item_c"]
      partition_field = null
      clustering      = null
      foreign_keys = [
        { column = "champion", table = "champions", references = "api_name" },
        { column = "item_a", table = "items", references = "api_name" },
        { column = "item_b", table = "items", references = "api_name" },
        { column = "item_c", table = "items", references = "api_name" },
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
    champion_item_pair_stats = {
      file        = "champion_item_pair_stats.sql.tftpl"
      vars        = {}
      description = "Per-patch stats for each champion + item pair derived from champion_item_pair_totals."
    }
    composition_stats = {
      file        = "composition_stats.sql.tftpl"
      vars        = {}
      description = "Per-patch comp stats derived from the compositions counters."
    }
    composition_variant_stats = {
      file        = "composition_variant_stats.sql.tftpl"
      vars        = {}
      description = "Per-patch stats for each comp variant derived from the composition_variants counters."
    }
    champion_item_trio_stats = {
      file        = "champion_item_trio_stats.sql.tftpl"
      vars        = {}
      description = "Per-patch stats for each champion + full 3-item build derived from champion_item_trio_totals."
    }
    composition_star_upgrade_stats = {
      file        = "composition_star_upgrade_stats.sql.tftpl"
      vars        = {}
      description = "Per-patch results of a comp's boards before and after each one-star upgrade of its units (2* -> 3* for 1-3 costs only), from composition_star_totals."
    }
    composition_completed_item_stats = {
      file        = "composition_board_stats.sql.tftpl"
      vars        = { totals = "composition_completed_item_totals", key = "completed_items" }
      description = "Per-patch stats of each comp's boards by completed items held, from composition_completed_item_totals."
    }
    composition_board_cost_stats = {
      file        = "composition_board_stats.sql.tftpl"
      vars        = { totals = "composition_board_cost_totals", key = "board_cost" }
      description = "Per-patch stats of each comp's boards by board cost, from composition_board_cost_totals."
    }
    composition_unit_stats = {
      file        = "composition_unit_stats.sql.tftpl"
      vars        = {}
      description = "Per-patch stats of each unit on a comp's boards, with the comp's boards without it as a baseline, from composition_star_totals."
    }
    composition_trait_stats = {
      file        = "composition_trait_stats.sql.tftpl"
      vars        = {}
      description = "Per-patch stats of each active trait on a comp's boards, with the comp's boards without it as a baseline, from composition_trait_totals."
    }
  }

  # What dashboards and LLM queries read: the latest patch only, with display names
  # (and the current ladder, which has no patch).
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
    current_champion_item_pair_stats = {
      file        = "current_champion_item_pair_stats.sql.tftpl"
      description = "champion_item_pair_stats for the latest patch, with names."
    }
    current_composition_stats = {
      file        = "current_composition_stats.sql.tftpl"
      description = "composition_stats for the latest patch."
    }
    current_matches = {
      file        = "current_matches.sql.tftpl"
      description = "Ranked matches of the latest patch, one row per game (no per-board data)."
    }
    current_participant_compositions = {
      file        = "current_participant_compositions.sql.tftpl"
      description = "Every ranked board of the latest patch: placement, level, gold, completed items and board cost, plus the comp it was assigned to (NULL if none). One row per player per match."
    }
    current_participant_units = {
      file        = "current_participant_units.sql.tftpl"
      description = "Every unit on every ranked board of the latest patch, with its star level, items and the board's placement. Large: filter on champion_name and select few columns."
    }
    current_composition_variant_stats = {
      file        = "current_composition_variant_stats.sql.tftpl"
      description = "composition_variant_stats for the latest patch."
    }
    current_champion_item_trio_stats = {
      file        = "current_champion_item_trio_stats.sql.tftpl"
      description = "champion_item_trio_stats for the latest patch, with names."
    }
    current_composition_star_upgrade_stats = {
      file        = "current_composition_star_upgrade_stats.sql.tftpl"
      description = "composition_star_upgrade_stats for the latest patch."
    }
    current_composition_completed_item_stats = {
      file        = "current_composition_completed_item_stats.sql.tftpl"
      description = "composition_completed_item_stats for the latest patch."
    }
    current_composition_board_cost_stats = {
      file        = "current_composition_board_cost_stats.sql.tftpl"
      description = "composition_board_cost_stats for the latest patch."
    }
    current_composition_unit_stats = {
      file        = "current_composition_unit_stats.sql.tftpl"
      description = "composition_unit_stats for the latest patch."
    }
    current_composition_trait_stats = {
      file        = "current_composition_trait_stats.sql.tftpl"
      description = "composition_trait_stats for the latest patch."
    }
    leaderboard = {
      file        = "leaderboard.sql.tftpl"
      description = "The current Challenger, Grandmaster and Master ladder per platform, without players who have left it."
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

# The 3-item builds on one champion, counted from the match tables on demand, for the web
# app (the SQL agent reads champion_item_trio_totals instead). It reads the per-match
# tables, so callers pass the patch's time window.
resource "google_bigquery_routine" "champion_item_trios" {
  dataset_id   = google_bigquery_dataset.tft.dataset_id
  routine_id   = "champion_item_trios"
  routine_type = "TABLE_VALUED_FUNCTION"
  language     = "SQL"
  description  = "Full 3-item builds on one champion in one patch, with display names and stats. Pass the patch's first and last ranked play time to prune partitions."
  definition_body = templatefile("${path.module}/bigquery/routines/champion_item_trios.sql.tftpl", {
    project         = var.project_id
    dataset         = google_bigquery_dataset.tft.dataset_id
    ranked_queue_id = 1100 # TFT_RANKED_QUEUE_ID in riot_api/constants.py
  })

  arguments {
    name      = "p_champion"
    data_type = jsonencode({ typeKind = "STRING" })
  }
  arguments {
    name      = "p_patch"
    data_type = jsonencode({ typeKind = "STRING" })
  }
  arguments {
    name      = "p_lo"
    data_type = jsonencode({ typeKind = "TIMESTAMP" })
  }
  arguments {
    name      = "p_hi"
    data_type = jsonencode({ typeKind = "TIMESTAMP" })
  }
  arguments {
    name      = "p_min_games"
    data_type = jsonencode({ typeKind = "INT64" })
  }

  depends_on = [google_bigquery_table.base, google_bigquery_table.linked]
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

"""Per-patch champion, trait and item stats, computed in BigQuery.

Each stats table is rebuilt by one SQL statement over every participant (board),
so there is no row cap and no Python-side scan.
"""

from google.cloud import bigquery

from db.bq import run_query, table_ref

# stats table -> (source table, column holding the api name, extra filter)
STATS_SOURCES = {
    "champion_stats": ("participant_units", "champion", ""),
    # Only traits that were actually active on the board
    "trait_stats": ("participant_traits", "trait", "WHERE tier_current > 0"),
    "item_stats": ("unit_items", "item", ""),
}


def stats_select_sql(client: bigquery.Client, stats_table: str) -> str:
    """The query behind one stats table, in the table's column order."""
    source, column, where = STATS_SOURCES[stats_table]
    return f"""
WITH boards AS (
  SELECT m.game_version AS patch, p.match_id, p.puuid, p.placement
  FROM `{table_ref(client, "participants")}` AS p
  JOIN `{table_ref(client, "matches")}` AS m USING (match_id)
),
totals AS (
  SELECT patch, COUNT(*) AS boards FROM boards GROUP BY patch
),
used AS (
  -- DISTINCT: two copies of a champion, or one item on two units, count once per board
  SELECT DISTINCT match_id, puuid, {column} AS api_name
  FROM `{table_ref(client, source)}`
  {where}
)
SELECT
  b.patch,
  u.api_name,
  COUNT(*) AS games,
  AVG(IF(b.placement = 1, 1, 0)) AS win_rate,
  AVG(IF(b.placement <= 4, 1, 0)) AS top4_rate,
  AVG(b.placement) AS average_placement,
  COUNT(*) / ANY_VALUE(totals.boards) AS play_rate,
  CURRENT_TIMESTAMP() AS updated_at
FROM used AS u
JOIN boards AS b USING (match_id, puuid)
JOIN totals USING (patch)
GROUP BY b.patch, u.api_name
"""


def stats_sql(client: bigquery.Client, stats_table: str) -> str:
    target = table_ref(client, stats_table)
    # The transaction swaps the table's contents atomically, so readers never see it empty
    return f"""
BEGIN TRANSACTION;
DELETE FROM `{target}` WHERE TRUE;
INSERT INTO `{target}`
  (patch, api_name, games, win_rate, top4_rate, average_placement, play_rate, updated_at)
{stats_select_sql(client, stats_table)};
COMMIT TRANSACTION;
"""


def refresh_stats(client: bigquery.Client, stats_table: str) -> None:
    run_query(client, stats_sql(client, stats_table))

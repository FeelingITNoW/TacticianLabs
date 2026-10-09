"""Full 3-item builds on one champion, for the SQL agent's `trios` tool.

Trios are too sparse to keep as counters (a unit's three items are its whole build), so
this counts them from the match tables on demand. The SQL is fixed and only takes
parameters, so the model never writes it. It reads just the latest patch's days (every
per-match table is partitioned on played_at), which a dry run estimated at ~1 GB four
days into a patch and grows with the patch, so it has its own, higher byte cap than
`sql`. Clustering on champion should cut the bytes actually billed; check the job history.
"""

from google.api_core import exceptions
from google.cloud import bigquery

from data_aggregation.data_aggregation import latest_patch, patch_window
from db.bq import table_ref
from insights.common import json_rows
from riot_api.constants import TFT_RANKED_QUEUE_ID

MAX_TRIOS = 50
MAX_BYTES_BILLED = 10_000_000_000

# Names of the tables it reads, filled in with table_ref
CHAMPION_SQL = """
SELECT api_name FROM `{champions}`
WHERE api_name = @champion OR LOWER(name) = LOWER(@champion)
LIMIT 1
"""

TRIOS_SQL = """
WITH builds AS (
  -- A unit holding exactly 3 items: its build, with the items in a fixed order
  SELECT u.match_id, u.puuid, ARRAY_AGG(i.item ORDER BY i.item) AS items
  FROM `{participant_units}` AS u
  JOIN `{unit_items}` AS i USING (match_id, puuid, slot)
  WHERE u.champion = @champion
    AND u.played_at BETWEEN @lo AND @hi
    AND i.played_at BETWEEN @lo AND @hi
  GROUP BY u.match_id, u.puuid, u.slot
  HAVING COUNT(*) = 3
),
boards AS (
  -- DISTINCT: two copies with the same build count once per board
  SELECT DISTINCT match_id, puuid, items[OFFSET(0)] AS item_a, items[OFFSET(1)] AS item_b,
    items[OFFSET(2)] AS item_c
  FROM builds
),
trios AS (
  SELECT
    b.item_a, b.item_b, b.item_c,
    COUNT(*) AS games,
    SAFE_DIVIDE(COUNTIF(p.placement = 1), COUNT(*)) AS win_rate,
    SAFE_DIVIDE(COUNTIF(p.placement <= 4), COUNT(*)) AS top4_rate,
    AVG(p.placement) AS average_placement
  FROM boards AS b
  JOIN `{participants}` AS p USING (match_id, puuid)
  JOIN `{matches}` AS m USING (match_id)
  WHERE p.played_at BETWEEN @lo AND @hi
    AND m.played_at BETWEEN @lo AND @hi
    AND m.game_version = @patch
    AND m.queue_id = {queue}
  GROUP BY b.item_a, b.item_b, b.item_c
  HAVING games >= @min_games
)
SELECT
  COALESCE(a.name, t.item_a) AS item_a,
  COALESCE(b.name, t.item_b) AS item_b,
  COALESCE(c.name, t.item_c) AS item_c,
  t.games, t.win_rate, t.top4_rate, t.average_placement,
  SAFE_DIVIDE(t.games, ch.boards) AS share_of_champion_games
FROM trios AS t
LEFT JOIN `{items}` AS a ON a.api_name = t.item_a
LEFT JOIN `{items}` AS b ON b.api_name = t.item_b
LEFT JOIN `{items}` AS c ON c.api_name = t.item_c
LEFT JOIN `{champion_totals}` AS ch ON ch.patch = @patch AND ch.api_name = @champion
ORDER BY t.average_placement
LIMIT {limit}
"""


def trios_sql(client: bigquery.Client) -> str:
    names = (
        "participant_units",
        "unit_items",
        "participants",
        "matches",
        "items",
        "champion_totals",
    )
    return TRIOS_SQL.format(
        **{name: table_ref(client, name) for name in names},
        queue=TFT_RANKED_QUEUE_ID,
        limit=MAX_TRIOS,
    )


def item_trios(
    client: bigquery.Client, champion: str, min_games: int, log: list[str]
) -> list[dict]:
    """The best 3-item builds on a champion in the latest patch, by average placement.

    `champion` is a name or api name. Problems come back as [{"error": ...}].
    """
    try:
        found = list(
            client.query(
                CHAMPION_SQL.format(champions=table_ref(client, "champions")),
                job_config=bigquery.QueryJobConfig(
                    query_parameters=[
                        bigquery.ScalarQueryParameter("champion", "STRING", champion)
                    ]
                ),
            ).result()
        )
        if not found:
            return [{"error": f"No champion called {champion!r}"}]
        patch = latest_patch(client)
        window = patch_window(client, patch) if patch else None
        if window is None:
            return [{"error": "No ranked matches yet"}]

        sql = trios_sql(client)
        log.append(sql)
        params = [
            bigquery.ScalarQueryParameter("champion", "STRING", found[0]["api_name"]),
            bigquery.ScalarQueryParameter("patch", "STRING", patch),
            bigquery.ScalarQueryParameter("lo", "TIMESTAMP", window[0]),
            bigquery.ScalarQueryParameter("hi", "TIMESTAMP", window[1]),
            bigquery.ScalarQueryParameter("min_games", "INT64", max(1, min_games)),
        ]
        job = client.query(
            sql,
            job_config=bigquery.QueryJobConfig(
                query_parameters=params, maximum_bytes_billed=MAX_BYTES_BILLED
            ),
        )
        return json_rows([dict(row) for row in job.result()])
    except (exceptions.BadRequest, exceptions.Forbidden) as exc:
        return [{"error": str(exc)}]

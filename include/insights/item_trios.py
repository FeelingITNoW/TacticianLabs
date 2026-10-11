"""Full 3-item builds on one champion, for the SQL agent's `trios` tool.

Trios are too sparse to keep as counters (a unit's three items are its whole build), so
they are counted from the match tables on demand by the BigQuery table function
`champion_item_trios` (infra/gcp/bigquery/routines/champion_item_trios.sql.tftpl), which
the web app calls too. This module resolves the champion, patch and time window and
passes them in as parameters, so the model never writes the SQL. Every per-match table is
partitioned on played_at and the function prunes by the window it is given: ~1 GB four
days into a patch, growing with the patch, so it has its own, higher byte cap than `sql`.
Clustering on champion should cut the bytes actually billed; check the job history.
"""

from google.api_core import exceptions
from google.cloud import bigquery

from data_aggregation.data_aggregation import latest_patch, patch_window
from db.bq import table_ref
from insights.common import json_rows

MAX_TRIOS = 50
MAX_BYTES_BILLED = 10_000_000_000

# Names of the tables it reads, filled in with table_ref
CHAMPION_SQL = """
SELECT api_name FROM `{champions}`
WHERE api_name = @champion OR LOWER(name) = LOWER(@champion)
LIMIT 1
"""

TRIOS_SQL = """
SELECT
  item_a_name AS item_a, item_b_name AS item_b, item_c_name AS item_c,
  games, win_rate, top4_rate, average_placement, share_of_champion_games
FROM `{trios}`(@champion, @patch, @lo, @hi, @min_games)
ORDER BY average_placement
LIMIT {limit}
"""


def trios_sql(client: bigquery.Client) -> str:
    return TRIOS_SQL.format(trios=table_ref(client, "champion_item_trios"), limit=MAX_TRIOS)


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

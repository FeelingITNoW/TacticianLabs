"""Cumulative per-patch counters for champions, traits, items and champion+item combos.

Every ingest write adds its matches' counts to the `*_totals` tables inside the
same transaction that inserts the matches, so nothing is ever re-scanned. The
counters are integers that sum across matches (boards, matches, placement sum,
top-4 and win counts), so rates derived from them in the stats views carry no
rounding error. `rebuild_totals` recomputes everything from the match tables for
a first backfill or recovery, and `check_totals` diffs the two.

A board is one player in one match. It counts once per entity however many copies
it holds, and `patch` is `matches.game_version`. Only ranked matches count: the match
tables also hold Challengers' normal games, which every count here leaves out.
"""

from collections.abc import Callable
from dataclasses import dataclass

from google.cloud import bigquery

from db.bq import run_query, table_ref
from riot_api.constants import TFT_RANKED_QUEUE_ID

# Maps a source table name to a SQL table expression
Resolver = Callable[[str], str]

BOARD_COUNTERS = ("boards", "matches", "placement_sum", "top4_count", "win_count")


@dataclass(frozen=True)
class Totals:
    keys: tuple[str, ...]  # key columns after `patch`
    # Rows (match_id, puuid, *keys) for every board that had the entity; one row per copy is fine
    source: Callable[[Resolver], str] | None
    # Counters in column order. patch_totals has its own.
    counters: tuple[str, ...] = BOARD_COUNTERS
    # Counters merged with GREATEST instead of added
    maxima: tuple[str, ...] = ()


TOTALS: dict[str, Totals] = {
    "champion_totals": Totals(
        ("api_name",),
        lambda t: f"SELECT match_id, puuid, champion AS api_name FROM {t('participant_units')}",
    ),
    # Only traits that were actually active on the board
    "trait_totals": Totals(
        ("api_name",),
        lambda t: (
            f"SELECT match_id, puuid, trait AS api_name FROM {t('participant_traits')} "
            "WHERE tier_current > 0"
        ),
    ),
    "item_totals": Totals(
        ("api_name",),
        lambda t: f"SELECT match_id, puuid, item AS api_name FROM {t('unit_items')}",
    ),
    "champion_item_totals": Totals(
        ("champion", "item"),
        lambda t: (
            "SELECT match_id, puuid, u.champion, i.item "
            f"FROM {t('participant_units')} AS u "
            f"JOIN {t('unit_items')} AS i USING (match_id, puuid, slot)"
        ),
    ),
    "patch_totals": Totals(
        (), None, counters=("matches", "boards", "last_played_at"), maxima=("last_played_at",)
    ),
}


# --- Table resolvers -------------------------------------------------------


def live_resolver(client: bigquery.Client) -> Resolver:
    """Every row in the real tables."""
    return lambda name: f"`{table_ref(client, name)}`"


def old_resolver(client: bigquery.Client) -> Resolver:
    """The rows write_match_rows is about to replace (its @match_ids/@lo/@hi parameters)."""
    return lambda name: (
        f"(SELECT * FROM `{table_ref(client, name)}` "
        "WHERE match_id IN UNNEST(@match_ids) AND played_at BETWEEN @lo AND @hi)"
    )


def new_resolver(client: bigquery.Client, staging: dict[str, str]) -> Resolver:
    """The rows staged for this write. Empty row lists were never staged, so they are empty."""
    return lambda name: (
        f"`{staging[name]}`"
        if name in staging
        else f"(SELECT * FROM `{table_ref(client, name)}` WHERE FALSE)"
    )


# --- Counting --------------------------------------------------------------


def value_columns(name: str) -> list[str]:
    """Columns counts_sql returns, in order (the table's columns minus updated_at)."""
    spec = TOTALS[name]
    return ["patch", *spec.keys, *spec.counters]


def counts_sql(name: str, t: Resolver, sign: int = 1) -> str:
    """One SELECT of per-patch counters over the tables `t` resolves, times `sign`."""
    spec = TOTALS[name]
    if spec.source is None:
        # patch_totals
        return f"""
SELECT
  m.game_version AS patch,
  {sign} * COUNT(DISTINCT m.match_id) AS matches,
  {sign} * COUNT(*) AS boards,
  MAX(m.played_at) AS last_played_at
FROM {t("matches")} AS m
JOIN {t("participants")} AS p USING (match_id)
WHERE m.queue_id = {TFT_RANKED_QUEUE_ID}
GROUP BY patch
"""
    keys = ", ".join(spec.keys)
    return f"""
WITH boards AS (
  SELECT m.game_version AS patch, p.match_id, p.puuid, p.placement
  FROM {t("participants")} AS p
  JOIN {t("matches")} AS m USING (match_id)
  WHERE m.queue_id = {TFT_RANKED_QUEUE_ID}
),
used AS (
  -- DISTINCT: two copies of a champion, or one item on two units, count once per board
  SELECT DISTINCT match_id, puuid, {keys}
  FROM ({spec.source(t)})
)
SELECT
  b.patch,
  {keys},
  {sign} * COUNT(*) AS boards,
  {sign} * COUNT(DISTINCT match_id) AS matches,
  {sign} * SUM(b.placement) AS placement_sum,
  {sign} * COUNTIF(b.placement <= 4) AS top4_count,
  {sign} * COUNTIF(b.placement = 1) AS win_count
FROM used AS u
JOIN boards AS b USING (match_id, puuid)
GROUP BY b.patch, {keys}
"""


def merge_sql(client: bigquery.Client, name: str, new: Resolver, old: Resolver) -> str:
    """Add the new rows' counts to `name` and subtract the rows they replace.

    Subtracting the old rows keeps a reload (or an overlapping re-ingest) from
    counting a match twice, and moves a match to its new patch if that changed.
    """
    spec = TOTALS[name]
    keys = ["patch", *spec.keys]
    counters = spec.counters
    on = " AND ".join(f"t.{k} = s.{k}" for k in keys)
    summed = ", ".join(
        f"{'MAX' if c in spec.maxima else 'SUM'}({c}) AS {c}" for c in counters
    )
    changed = " OR ".join(
        f"{c} != 0" for c in counters if c not in spec.maxima
    )
    updates = ", ".join(
        f"{c} = GREATEST(t.{c}, s.{c})" if c in spec.maxima else f"{c} = t.{c} + s.{c}"
        for c in counters
    )
    columns = ", ".join([*keys, *counters, "updated_at"])
    values = ", ".join([*(f"s.{c}" for c in [*keys, *counters]), "CURRENT_TIMESTAMP()"])
    return f"""
MERGE `{table_ref(client, name)}` AS t
USING (
  SELECT {", ".join(keys)}, {summed}
  FROM (
    ({counts_sql(name, new)})
    UNION ALL
    ({counts_sql(name, old, sign=-1)})
  )
  GROUP BY {", ".join(keys)}
  HAVING {changed}
) AS s
ON {on}
WHEN MATCHED AND t.boards + s.boards <= 0 THEN DELETE
WHEN MATCHED THEN UPDATE SET {updates}, updated_at = CURRENT_TIMESTAMP()
WHEN NOT MATCHED AND s.boards > 0 THEN INSERT ({columns}) VALUES ({values});
"""


def merge_totals_sql(client: bigquery.Client, staging: dict[str, str]) -> list[str]:
    """Statements that fold one write's matches into every totals table.

    They must run before the write's deletes (they read the rows being replaced)
    and inside the same transaction, so counters and matches commit together.
    """
    new = new_resolver(client, staging)
    old = old_resolver(client)
    return [merge_sql(client, name, new, old) for name in TOTALS]


# --- Rebuild and check -----------------------------------------------------


def rebuild_sql(client: bigquery.Client) -> str:
    """Recompute every totals table from the match tables in one transaction."""
    live = live_resolver(client)
    statements = ["BEGIN TRANSACTION;"]
    for name in TOTALS:
        columns = ", ".join([*value_columns(name), "updated_at"])
        statements.append(f"DELETE FROM `{table_ref(client, name)}` WHERE TRUE;")
        statements.append(
            f"INSERT INTO `{table_ref(client, name)}` ({columns})\n"
            f"SELECT *, CURRENT_TIMESTAMP() FROM ({counts_sql(name, live)});"
        )
    statements.append("COMMIT TRANSACTION;")
    return "\n".join(statements)


def rebuild_totals(client: bigquery.Client) -> None:
    run_query(client, rebuild_sql(client))


def check_sql(client: bigquery.Client, name: str) -> str:
    columns = ", ".join(value_columns(name))
    target = f"SELECT {columns} FROM `{table_ref(client, name)}`"
    return f"""
WITH computed AS ({counts_sql(name, live_resolver(client))})
SELECT COUNT(*) AS mismatches FROM (
  (SELECT {columns} FROM computed EXCEPT DISTINCT {target})
  UNION ALL
  ({target} EXCEPT DISTINCT SELECT {columns} FROM computed)
)
"""


def check_totals(client: bigquery.Client) -> dict[str, int]:
    """Rows where each totals table disagrees with a fresh recount (all zero when healthy)."""
    return {
        name: run_query(client, check_sql(client, name))[0]["mismatches"]
        for name in TOTALS
    }


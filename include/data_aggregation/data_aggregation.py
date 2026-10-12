"""Cumulative per-patch counters for champions, traits, items, champion+item combos, pairs
and trios, and for comps' boards by star level, completed items and board cost.

Every ingest write adds its matches' counts to the `*_totals` tables inside the
same transaction that inserts the matches, so nothing is ever re-scanned. The
composition_* totals are the exception: they count boards by the comp they were
assigned to, which only the clustering job knows, so it rebuilds the patch's rows in
the transaction that writes the comps (see Totals.clustered). The
counters are integers that sum across matches (boards, matches, placement sum,
top-4 and win counts), so rates derived from them in the stats views carry no
rounding error. `rebuild_totals` recomputes everything from the match tables for
a first backfill or recovery (all patches, or one patch of chosen tables, which only
reads that patch's days), and `check_totals` diffs the two.

A board is one player in one match. It counts once per entity however many copies
it holds, and `patch` is `matches.game_version`. Only ranked matches count: the match
tables also hold Challengers' normal games, which every count here leaves out.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime

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
    # Counts boards by participant_compositions: rebuilt by the clustering job, never
    # merged by ingest writes (which don't know the comps)
    clustered: bool = False


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
    # Two items on the same unit, as an unordered pair (item_a <= item_b), so two copies
    # of one item are a valid pair. A unit with 3 items has 3 pairs.
    "champion_item_pair_totals": Totals(
        ("champion", "item_a", "item_b"),
        lambda t: (
            "SELECT match_id, puuid, u.champion, "
            "LEAST(a.item, b.item) AS item_a, GREATEST(a.item, b.item) AS item_b "
            f"FROM {t('participant_units')} AS u "
            f"JOIN {t('unit_items')} AS a USING (match_id, puuid, slot) "
            f"JOIN {t('unit_items')} AS b USING (match_id, puuid, slot) "
            "WHERE a.item_index < b.item_index"
        ),
    ),
    # A unit's full build: exactly 3 items, in api-name order (item_a <= item_b <= item_c)
    "champion_item_trio_totals": Totals(
        ("champion", "item_a", "item_b", "item_c"),
        lambda t: (
            "SELECT match_id, puuid, champion, items[OFFSET(0)] AS item_a, "
            "items[OFFSET(1)] AS item_b, items[OFFSET(2)] AS item_c "
            "FROM (SELECT u.match_id, u.puuid, u.champion, ARRAY_AGG(i.item ORDER BY i.item) AS items "
            f"FROM {t('participant_units')} AS u "
            f"JOIN {t('unit_items')} AS i USING (match_id, puuid, slot) "
            "GROUP BY u.match_id, u.puuid, u.slot, u.champion "
            "HAVING COUNT(*) = 3)"
        ),
    ),
    # A comp's boards by each unit's star level: the highest copy's, so a board counts once per unit
    "composition_star_totals": Totals(
        ("comp_id", "champion", "star"),
        lambda t: (
            "SELECT pc.match_id, pc.puuid, pc.comp_id, u.champion, MAX(u.star) AS star "
            f"FROM {t('participant_compositions')} AS pc "
            f"JOIN {t('participant_units')} AS u USING (match_id, puuid) "
            "WHERE u.star IS NOT NULL "
            "GROUP BY pc.match_id, pc.puuid, pc.comp_id, u.champion"
        ),
        clustered=True,
    ),
    "composition_completed_item_totals": Totals(
        ("comp_id", "completed_items"),
        lambda t: (
            "SELECT pc.match_id, pc.puuid, pc.comp_id, p.completed_items "
            f"FROM {t('participant_compositions')} AS pc "
            f"JOIN {t('participants')} AS p USING (match_id, puuid) "
            "WHERE p.completed_items IS NOT NULL"
        ),
        clustered=True,
    ),
    "composition_board_cost_totals": Totals(
        ("comp_id", "board_cost"),
        lambda t: (
            "SELECT pc.match_id, pc.puuid, pc.comp_id, p.board_cost "
            f"FROM {t('participant_compositions')} AS pc "
            f"JOIN {t('participants')} AS p USING (match_id, puuid) "
            "WHERE p.board_cost IS NOT NULL"
        ),
        clustered=True,
    ),
    # Active traits on a comp's boards, by tier. A board has one row per trait, so the tier
    # rows of a trait are disjoint and summing them gives the boards that had it active.
    "composition_trait_totals": Totals(
        ("comp_id", "trait", "tier"),
        lambda t: (
            "SELECT pc.match_id, pc.puuid, pc.comp_id, tr.trait, tr.tier_current AS tier "
            f"FROM {t('participant_compositions')} AS pc "
            f"JOIN {t('participant_traits')} AS tr USING (match_id, puuid) "
            "WHERE tr.tier_current > 0"
        ),
        clustered=True,
    ),
    "patch_totals": Totals(
        (),
        None,
        counters=(
            "matches",
            "boards",
            "last_played_at",
            "placement_sum",
            "top4_count",
            "win_count",
        ),
        maxima=("last_played_at",),
    ),
}

# What ingest writes merge into, and what the clustering job rebuilds
INGEST_TOTALS = [name for name, spec in TOTALS.items() if not spec.clustered]
COMPOSITION_TOTALS = [name for name, spec in TOTALS.items() if spec.clustered]


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


def window_resolver(client: bigquery.Client) -> Resolver:
    """Rows played inside @lo..@hi: every per-match table is partitioned on played_at,
    so a rebuild of one patch only reads that patch's days."""
    return lambda name: (
        f"(SELECT * FROM `{table_ref(client, name)}` "
        "WHERE played_at BETWEEN @lo AND @hi)"
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
  MAX(m.played_at) AS last_played_at,
  {sign} * SUM(p.placement) AS placement_sum,
  {sign} * COUNTIF(p.placement <= 4) AS top4_count,
  {sign} * COUNTIF(p.placement = 1) AS win_count
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
    """Statements that fold one write's matches into every totals table but the clustered ones.

    They must run before the write's deletes (they read the rows being replaced)
    and inside the same transaction, so counters and matches commit together.
    """
    new = new_resolver(client, staging)
    old = old_resolver(client)
    return [merge_sql(client, name, new, old) for name in INGEST_TOTALS]


# --- Rebuild and check -----------------------------------------------------


def latest_patch(client: bigquery.Client) -> str | None:
    """The newest patch, by the same rule as the current_* views."""
    rows = run_query(
        client,
        f"SELECT patch FROM `{table_ref(client, 'patch_totals')}` "
        "ORDER BY last_played_at DESC LIMIT 1",
    )
    return rows[0]["patch"] if rows else None


def patch_window(client: bigquery.Client, patch: str) -> tuple[datetime, datetime] | None:
    """First and last play time of the patch's ranked matches, or None if it has none."""
    rows = run_query(
        client,
        f"""
SELECT MIN(played_at) AS lo, MAX(played_at) AS hi
FROM `{table_ref(client, "matches")}`
WHERE game_version = @patch AND queue_id = {TFT_RANKED_QUEUE_ID}
""",
        [bigquery.ScalarQueryParameter("patch", "STRING", patch)],
    )
    if not rows or rows[0]["lo"] is None:
        return None
    return rows[0]["lo"], rows[0]["hi"]


def patch_params(client: bigquery.Client, patch: str) -> list[bigquery.ScalarQueryParameter]:
    """@patch, @lo and @hi for a rebuild or check of one patch."""
    window = patch_window(client, patch)
    if window is None:
        raise ValueError(f"No ranked matches for patch {patch}")
    return [
        bigquery.ScalarQueryParameter("patch", "STRING", patch),
        bigquery.ScalarQueryParameter("lo", "TIMESTAMP", window[0]),
        bigquery.ScalarQueryParameter("hi", "TIMESTAMP", window[1]),
    ]


def _selected(tables: Sequence[str] | None) -> list[str]:
    names = list(tables) if tables else list(TOTALS)
    unknown = set(names) - set(TOTALS)
    if unknown:
        raise ValueError(f"Unknown totals tables: {sorted(unknown)}")
    return names


def rebuild_statements(
    client: bigquery.Client, tables: Sequence[str] | None = None, patch: bool = False
) -> list[str]:
    """The DELETE and INSERT per table that rebuild_sql wraps in a transaction."""
    resolver = window_resolver(client) if patch else live_resolver(client)
    statements = []
    for name in _selected(tables):
        columns = ", ".join([*value_columns(name), "updated_at"])
        scope = " WHERE patch = @patch" if patch else ""
        statements.append(
            f"DELETE FROM `{table_ref(client, name)}` WHERE {'patch = @patch' if patch else 'TRUE'};"
        )
        statements.append(
            f"INSERT INTO `{table_ref(client, name)}` ({columns})\n"
            f"SELECT *, CURRENT_TIMESTAMP() FROM ({counts_sql(name, resolver)}){scope};"
        )
    return statements


def rebuild_sql(
    client: bigquery.Client, tables: Sequence[str] | None = None, patch: bool = False
) -> str:
    """Recompute totals tables from the match tables in one transaction.

    By default every table, every patch. `tables` limits which tables. With `patch`
    only the rows of the patch in @patch are replaced, counted from the days in
    @lo..@hi (see patch_params), so older patches' rows are left alone.
    """
    statements = rebuild_statements(client, tables, patch)
    return "\n".join(["BEGIN TRANSACTION;", *statements, "COMMIT TRANSACTION;"])


def rebuild_totals(
    client: bigquery.Client, tables: Sequence[str] | None = None, patch: str | None = None
) -> None:
    """Rebuild the totals tables (see rebuild_sql); `patch` limits it to that patch.

    Raises ValueError for an unknown table or a patch with no ranked matches.
    """
    params = patch_params(client, patch) if patch else ()
    run_query(client, rebuild_sql(client, tables, patch=bool(patch)), params)


def check_sql(client: bigquery.Client, name: str, patch: bool = False) -> str:
    columns = ", ".join(value_columns(name))
    scope = " WHERE patch = @patch" if patch else ""
    computed = counts_sql(name, window_resolver(client) if patch else live_resolver(client))
    if patch:
        computed = f"SELECT * FROM ({computed}){scope}"
    target = f"SELECT {columns} FROM `{table_ref(client, name)}`{scope}"
    return f"""
WITH computed AS ({computed})
SELECT COUNT(*) AS mismatches FROM (
  (SELECT {columns} FROM computed EXCEPT DISTINCT {target})
  UNION ALL
  ({target} EXCEPT DISTINCT SELECT {columns} FROM computed)
)
"""


def check_totals(
    client: bigquery.Client, tables: Sequence[str] | None = None, patch: str | None = None
) -> dict[str, int]:
    """Rows where each totals table disagrees with a fresh recount (all zero when healthy).

    `tables` and `patch` scope it the same way as rebuild_totals.
    """
    params = patch_params(client, patch) if patch else ()
    return {
        name: run_query(client, check_sql(client, name, patch=bool(patch)), params)[0][
            "mismatches"
        ]
        for name in _selected(tables)
    }

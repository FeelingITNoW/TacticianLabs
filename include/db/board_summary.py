"""Board summaries stored on participants: completed_items and board_cost.

Both come from the reference tables, so like the stored names (db.reference_names)
they are filled in SQL rather than by the parser:

- completed_items: items held across the board that aren't components
  (items.item_type <> 'component'): standard completed items, emblems, artifacts and
  radiants. An item missing from items counts as completed.
- board_cost: the gold the board's units are worth, each unit's champions.cost times
  the copies its star level takes (3 ** (star - 1), so 1, 3 or 9). A champion missing
  from champions (summons, an unseeded set) counts as 0.

write_match_rows fills them from the staged units and items as it inserts participants
(insert_participants_sql), and backfill_board_summary_sql refreshes stored rows: ones
written before the columns existed, or before a reseed changed a cost or item type.
A board with no units or no items gets 0.
"""

from google.cloud import bigquery

from db.bq import column_names, table_ref

BOARD_COLUMNS = ("completed_items", "board_cost")


def _board_summary(
    client: bigquery.Client, participants: str, units: str | None, items: str | None
) -> tuple[dict[str, str], str]:
    """(SQL expression per board column, FROM clause over `participants` AS s).

    `units` and `items` are tables shaped like participant_units and unit_items; None
    when there are none, which makes that column 0.
    """
    expressions = {column: "0" for column in BOARD_COLUMNS}
    clauses = [f"FROM `{participants}` AS s"]
    if items:
        expressions["completed_items"] = "COALESCE(ci.completed_items, 0)"
        clauses.append(
            "LEFT JOIN (\n"
            "  SELECT i.match_id, i.puuid,\n"
            "    COUNTIF(r.item_type IS DISTINCT FROM 'component') AS completed_items\n"
            f"  FROM `{items}` AS i\n"
            f"  LEFT JOIN `{table_ref(client, 'items')}` AS r ON r.api_name = i.item\n"
            "  GROUP BY i.match_id, i.puuid\n"
            ") AS ci ON ci.match_id = s.match_id AND ci.puuid = s.puuid"
        )
    if units:
        expressions["board_cost"] = "COALESCE(bc.board_cost, 0)"
        clauses.append(
            "LEFT JOIN (\n"
            "  SELECT u.match_id, u.puuid,\n"
            "    SUM(COALESCE(c.cost, 0) * CAST(POW(3, COALESCE(u.star, 1) - 1) AS INT64)) AS board_cost\n"
            f"  FROM `{units}` AS u\n"
            f"  LEFT JOIN `{table_ref(client, 'champions')}` AS c ON c.api_name = u.champion\n"
            "  GROUP BY u.match_id, u.puuid\n"
            ") AS bc ON bc.match_id = s.match_id AND bc.puuid = s.puuid"
        )
    return expressions, "\n".join(clauses)


def insert_participants_sql(client: bigquery.Client, staging: dict[str, str]) -> str:
    """Insert the staged participants with their board summary worked out from the
    staged participant_units and unit_items (`staging` maps table -> staging table).

    The columns come from the live table, so before the board columns exist this is a
    plain insert.
    """
    expressions, source = _board_summary(
        client,
        staging["participants"],
        staging.get("participant_units"),
        staging.get("unit_items"),
    )
    columns = column_names(client, "participants")
    values = ", ".join(
        f"{expressions[c]} AS {c}" if c in expressions else f"s.{c}" for c in columns
    )
    return (
        f"INSERT INTO `{table_ref(client, 'participants')}` ({', '.join(columns)})\n"
        f"SELECT {values}\n{source};"
    )


def backfill_board_summary_sql(client: bigquery.Client) -> str:
    """Recount every stored board and rewrite the rows whose summary is missing or
    differs. (match_id, puuid) is unique, so each row joins at most one summary."""
    expressions, source = _board_summary(
        client,
        table_ref(client, "participants"),
        table_ref(client, "participant_units"),
        table_ref(client, "unit_items"),
    )
    summary = ", ".join(f"{expressions[c]} AS {c}" for c in BOARD_COLUMNS)
    sets = ", ".join(f"{c} = b.{c}" for c in BOARD_COLUMNS)
    changed = " OR ".join(f"t.{c} IS DISTINCT FROM b.{c}" for c in BOARD_COLUMNS)
    return (
        f"UPDATE `{table_ref(client, 'participants')}` AS t SET {sets}\n"
        f"FROM (\nSELECT s.match_id, s.puuid, {summary}\n{source}\n) AS b\n"
        f"WHERE t.match_id = b.match_id AND t.puuid = b.puuid AND ({changed});"
    )

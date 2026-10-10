"""Display names stored next to the api names in the per-match tables.

Riot match payloads only carry api names (e.g. DA_18_KhaZix), so the names come from
the champions/items reference tables. write_match_rows copies them in as it inserts
(insert_with_names_sql), and backfill_names refreshes rows already stored: ones written
before their reference row existed, before the columns were added, or before a name
changed on reseed. An api name missing from its reference table leaves the name NULL.
"""

from collections.abc import Sequence

from google.cloud import bigquery

from db.bq import column_names, run_query, table_ref

# Per-match table -> (name column, api name column, reference table)
NAME_COLUMNS: dict[str, tuple[str, str, str]] = {
    "participant_units": ("champion_name", "champion", "champions"),
    "unit_items": ("item_name", "item", "items"),
}


def insert_with_names_sql(client: bigquery.Client, name: str, staging_id: str) -> str:
    """Like insert_from_staging_sql, with the name column looked up in the reference table.

    The columns come from the live table, so before the name column exists this is a
    plain insert.
    """
    name_column, key, reference = NAME_COLUMNS[name]
    columns = column_names(client, name)
    values = ", ".join(
        f"r.name AS {c}" if c == name_column else f"s.{c}" for c in columns
    )
    return (
        f"INSERT INTO `{table_ref(client, name)}` ({', '.join(columns)})\n"
        f"SELECT {values} FROM `{staging_id}` AS s\n"
        f"LEFT JOIN `{table_ref(client, reference)}` AS r ON r.api_name = s.{key};"
    )


def backfill_names_sql(client: bigquery.Client, name: str) -> str:
    """Set the name on every row whose name is missing or differs from the reference
    table. api_name is unique there, so each row joins at most one name."""
    name_column, key, reference = NAME_COLUMNS[name]
    return (
        f"UPDATE `{table_ref(client, name)}` AS t SET {name_column} = r.name\n"
        f"FROM `{table_ref(client, reference)}` AS r\n"
        f"WHERE t.{key} = r.api_name AND t.{name_column} IS DISTINCT FROM r.name;"
    )


def backfill_names(
    client: bigquery.Client, tables: Sequence[str] | None = None
) -> None:
    """Refresh the name columns of `tables` (default all of NAME_COLUMNS). Safe to repeat,
    and to run alongside an ingest: run_query retries concurrent DML aborts."""
    script = "\n".join(backfill_names_sql(client, name) for name in tables or NAME_COLUMNS)
    run_query(client, script)

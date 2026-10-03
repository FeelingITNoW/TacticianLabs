"""
Populate the champions, traits, and items reference tables for the current set.

Rows are keyed on Riot's api name (e.g. DA_ArchangelsStaff), which match payloads
use and which stays the same across patches. Each run replaces a table's contents.
Source: the root tft-*.json Data Dragon files (version 16.19.1).

Usage:
    PYTHONPATH=include python -m db.seed_reference_data
"""

import json
from pathlib import Path

from dotenv import load_dotenv
from google.cloud import bigquery

from db.bq import insert_from_staging_sql, make_client, run_query, staged, table_ref

WORKSPACE_ROOT = Path(__file__).parent.parent.parent

TFT_SET = 18
# Set 18 api names start with "DA_" (e.g. DA_18_KhaZix, DA_18_Brawler,
# DA_ArchangelsStaff) rather than the "TFT<set>_" prefix earlier sets used.
SET_ID_PREFIX = "DA_"


def _entries(filename: str) -> list[dict]:
    with open(WORKSPACE_ROOT / filename) as f:
        data = json.load(f)
    return sorted(
        (
            v
            for v in data["data"].values()
            if v["id"].startswith(SET_ID_PREFIX)
            and v["name"]  # skip entries with empty display names
        ),
        key=lambda v: v["id"],
    )


def _load_champions() -> list[dict]:
    return [
        {"api_name": v["id"], "name": v["name"], "cost": v.get("cost")}
        for v in _entries("tft-champion.json")
    ]


def _load_traits() -> list[dict]:
    return [
        {"api_name": v["id"], "name": v["name"]} for v in _entries("tft-trait.json")
    ]


def _load_items() -> list[dict]:
    return [{"api_name": v["id"], "name": v["name"]} for v in _entries("tft-item.json")]


def seed_reference_data(client: bigquery.Client) -> None:
    for table, rows in (
        ("champions", _load_champions()),
        ("traits", _load_traits()),
        ("items", _load_items()),
    ):
        print(f"Seeding {len(rows)} set {TFT_SET} {table}...")
        # Swap contents in a transaction rather than a WRITE_TRUNCATE load, which
        # would replace the table's metadata along with its rows.
        with staged(client, {table: rows}) as staging:
            run_query(
                client,
                "BEGIN TRANSACTION;\n"
                f"DELETE FROM `{table_ref(client, table)}` WHERE TRUE;\n"
                f"{insert_from_staging_sql(client, table, staging[table])}\n"
                "COMMIT TRANSACTION;",
            )


if __name__ == "__main__":
    load_dotenv()
    seed_reference_data(make_client())
    print("Done.")

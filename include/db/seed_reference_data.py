"""
Populate the champions, traits, and items reference tables for the current set.

Rows are keyed on Riot's api name (e.g. DA_ArchangelsStaff), which match payloads
use and which stays the same across patches. Each run adds new rows and updates
existing ones, and never deletes, so names still resolve for older patches' stats.
It then refreshes the names stored on the match tables (db.reference_names).
Source: the root tft-*.json Data Dragon files (version 16.19.1).

Usage:
    PYTHONPATH=include python -m db.seed_reference_data
"""

import json
from pathlib import Path

from dotenv import load_dotenv
from google.cloud import bigquery

from db.bq import column_names, make_client, run_query, staged, table_ref
from db.reference_names import backfill_names

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


def item_type(api_name: str) -> str:
    """Kind of item, read from the api name since Data Dragon has no category field:
    artifact (DA_Artifact_*, DA_Item_Artifact_*), radiant (ends in Radiant),
    component (DA_Component_*), emblem (DA_18_Emblem*), else other. Other holds the
    standard completed items plus boosters, consumables, chests and the Tactician's items."""
    if "Artifact" in api_name:
        return "artifact"
    if api_name.endswith("Radiant"):
        return "radiant"
    if api_name.startswith("DA_Component_"):
        return "component"
    if api_name.startswith("DA_18_Emblem"):
        return "emblem"
    return "other"


def _load_items() -> list[dict]:
    return [
        {"api_name": v["id"], "name": v["name"], "item_type": item_type(v["id"])}
        for v in _entries("tft-item.json")
    ]


def merge_reference_sql(client: bigquery.Client, table: str, staging_id: str) -> str:
    columns = column_names(client, table)
    updates = ", ".join(f"{c} = s.{c}" for c in columns if c != "api_name")
    return (
        f"MERGE `{table_ref(client, table)}` AS t USING `{staging_id}` AS s "
        "ON t.api_name = s.api_name\n"
        f"WHEN MATCHED THEN UPDATE SET {updates}\n"
        f"WHEN NOT MATCHED THEN INSERT ({', '.join(columns)}) "
        f"VALUES ({', '.join(f's.{c}' for c in columns)});"
    )


def seed_reference_data(client: bigquery.Client) -> None:
    for table, rows in (
        ("champions", _load_champions()),
        ("traits", _load_traits()),
        ("items", _load_items()),
    ):
        print(f"Seeding {len(rows)} set {TFT_SET} {table}...")
        with staged(client, {table: rows}) as staging:
            run_query(client, merge_reference_sql(client, table, staging[table]))
    print("Backfilling champion and item names on the match tables...")
    backfill_names(client)


if __name__ == "__main__":
    load_dotenv()
    seed_reference_data(make_client())
    print("Done.")

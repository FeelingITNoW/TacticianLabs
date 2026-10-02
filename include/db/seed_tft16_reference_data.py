"""
One-time script to populate the champions, traits, and items reference tables.

Rows are keyed on Riot's api name (e.g. TFT_Item_BFSword), which match payloads
use and which stays the same across patches. Each run replaces a table's contents.

Usage:
    PYTHONPATH=include python -m db.seed_tft16_reference_data
"""

import json
from pathlib import Path

from dotenv import load_dotenv

from db.bq import insert_from_staging_sql, make_client, run_query, staged, table_ref

WORKSPACE_ROOT = Path(__file__).parent.parent.parent


def _load_tft16_champions() -> list[dict]:
    with open(WORKSPACE_ROOT / "tft-champion.json") as f:
        data = json.load(f)

    # Only set 16 champions (id starts with TFT16_)
    return sorted(
        [
            {"api_name": v["id"], "name": v["name"], "cost": v.get("cost")}
            for v in data["data"].values()
            if v["id"].startswith("TFT16_")
        ],
        key=lambda row: row["api_name"],
    )


def _load_tft16_traits() -> list[dict]:
    with open(WORKSPACE_ROOT / "tft-trait.json") as f:
        data = json.load(f)

    # Only set 16 traits (id starts with TFT16_)
    return sorted(
        [
            {"api_name": v["id"], "name": v["name"]}
            for v in data["data"].values()
            if v["id"].startswith("TFT16_")
        ],
        key=lambda row: row["api_name"],
    )


def _load_items() -> list[dict]:
    with open(WORKSPACE_ROOT / "tft-item.json") as f:
        data = json.load(f)

    # Equippable items: contain _Item_ in id, exclude Consumables and Tutorial items
    return sorted(
        [
            {"api_name": v["id"], "name": v["name"]}
            for v in data["data"].values()
            if "_Item_" in v["id"]
            and "Consumable" not in v["id"]
            and "Tutorial" not in v["id"]
            and v["name"]  # skip entries with empty display names
        ],
        key=lambda row: row["api_name"],
    )


def seed_reference_data() -> None:
    load_dotenv()
    client = make_client()

    for table, rows in (
        ("champions", _load_tft16_champions()),
        ("traits", _load_tft16_traits()),
        ("items", _load_items()),
    ):
        print(f"Seeding {len(rows)} {table}...")
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

    print("Done.")


if __name__ == "__main__":
    seed_reference_data()

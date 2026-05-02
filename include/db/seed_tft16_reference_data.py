"""
One-time script to populate the champions, traits, and items reference tables.

Run this before the calculate_tft_stats DAG so it has data to iterate over.

Usage:
    python include/db/seed_tft16_reference_data.py
"""

import json
import os
from pathlib import Path

from dotenv import load_dotenv
from supabase import create_client

WORKSPACE_ROOT = Path(__file__).parent.parent.parent


def _load_tft16_champions() -> list[dict]:
    with open(WORKSPACE_ROOT / "tft-champion.json") as f:
        data = json.load(f)

    # Only set 16 champions (id starts with TFT16_)
    entries = sorted(
        [v for v in data["data"].values() if v["id"].startswith("TFT16_")],
        key=lambda v: v["id"],
    )
    return [
        {"champion_id": i + 1, "name": entry["id"]} for i, entry in enumerate(entries)
    ]


def _load_tft16_traits() -> list[dict]:
    with open(WORKSPACE_ROOT / "tft-trait.json") as f:
        data = json.load(f)

    # Only set 16 traits (id starts with TFT16_)
    entries = sorted(
        [v for v in data["data"].values() if v["id"].startswith("TFT16_")],
        key=lambda v: v["id"],
    )
    return [{"trait_id": i + 1, "name": entry["id"]} for i, entry in enumerate(entries)]


def _load_items() -> list[dict]:
    with open(WORKSPACE_ROOT / "tft-item.json") as f:
        data = json.load(f)

    # Equippable items: contain _Item_ in id, exclude Consumables and Tutorial items
    entries = sorted(
        [
            v
            for v in data["data"].values()
            if "_Item_" in v["id"]
            and "Consumable" not in v["id"]
            and "Tutorial" not in v["id"]
            and v["name"]  # skip entries with empty display names
        ],
        key=lambda v: v["id"],
    )
    return [{"item_id": i + 1, "name": entry["id"]} for i, entry in enumerate(entries)]


def seed_reference_data() -> None:
    load_dotenv()
    supabase = create_client(
        os.environ["supabase_url"],
        os.environ["supabase_key"],
    )

    champions = _load_tft16_champions()
    traits = _load_tft16_traits()
    items = _load_items()

    print(f"Seeding {len(champions)} TFT16 champions...")
    supabase.table("champions").upsert(champions).execute()

    print(f"Seeding {len(traits)} TFT16 traits...")
    supabase.table("traits").upsert(traits).execute()

    print(f"Seeding {len(items)} items (non-consumable)...")
    supabase.table("items").upsert(items).execute()

    print("Done.")


if __name__ == "__main__":
    seed_reference_data()

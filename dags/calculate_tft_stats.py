import os
from datetime import datetime

from airflow.sdk import dag, task  # type: ignore

from data_aggregation.data_aggregation import (
    _calculate_stat,
    get_all_participants_with_item,
    get_all_participants_with_trait,
    get_all_participants_with_unit,
    get_num_of_all_participants,
)


@dag(
    dag_id="calculate_tft_stats",
    schedule="@daily",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    default_args={"owner": "Astro", "retries": 3},
    tags=["stats"],
)
def calculate_tft_stats():

    @task
    def fetch_units_task() -> list[dict]:
        from supabase import create_client

        supabase = create_client(
            os.environ["supabase_url"],
            os.environ["supabase_key"],
        )
        response = supabase.table("champions").select("champion_id, name").execute()
        return response.data

    @task
    def fetch_traits_task() -> list[dict]:
        from supabase import create_client

        supabase = create_client(
            os.environ["supabase_url"],
            os.environ["supabase_key"],
        )
        response = supabase.table("traits").select("trait_id, name").execute()
        return response.data

    @task
    def fetch_items_task() -> list[dict]:
        from supabase import create_client

        supabase = create_client(
            os.environ["supabase_url"],
            os.environ["supabase_key"],
        )
        response = supabase.table("items").select("item_id, name").execute()
        return response.data

    @task
    def calculate_unit_stats_task(unit: dict) -> None:
        from supabase import create_client

        supabase = create_client(
            os.environ["supabase_url"],
            os.environ["supabase_key"],
        )
        total = get_num_of_all_participants(supabase)
        participants = get_all_participants_with_unit(supabase, unit["name"])
        stats = {
            "champion_id": unit["champion_id"],
            "win_rate": _calculate_stat(participants, "win_rate"),
            "top4_rate": _calculate_stat(participants, "top4_rate"),
            "average_placement": _calculate_stat(participants, "average_placement"),
            "play_rate": _calculate_stat(
                participants, "play_rate", total_participants=total
            ),
        }
        supabase.table("champion_stats").upsert(stats).execute()
        print(f"Upserted stats for champion {unit['name']}: {stats}")

    @task
    def calculate_trait_stats_task(trait: dict) -> None:
        from supabase import create_client

        supabase = create_client(
            os.environ["supabase_url"],
            os.environ["supabase_key"],
        )
        total = get_num_of_all_participants(supabase)
        participants = get_all_participants_with_trait(supabase, trait["name"])
        stats = {
            "trait_id": trait["trait_id"],
            "win_rate": _calculate_stat(participants, "win_rate"),
            "top4_rate": _calculate_stat(participants, "top4_rate"),
            "average_placement": _calculate_stat(participants, "average_placement"),
            "play_rate": _calculate_stat(
                participants, "play_rate", total_participants=total
            ),
        }
        supabase.table("trait_stats").upsert(stats).execute()
        print(f"Upserted stats for trait {trait['name']}: {stats}")

    @task
    def calculate_item_stats_task(item: dict) -> None:
        from supabase import create_client

        supabase = create_client(
            os.environ["supabase_url"],
            os.environ["supabase_key"],
        )
        total = get_num_of_all_participants(supabase)
        participants = get_all_participants_with_item(supabase, item["name"])
        stats = {
            "item_id": item["item_id"],
            "win_rate": _calculate_stat(participants, "win_rate"),
            "top4_rate": _calculate_stat(participants, "top4_rate"),
            "average_placement": _calculate_stat(participants, "average_placement"),
            "play_rate": _calculate_stat(
                participants, "play_rate", total_participants=total
            ),
        }
        supabase.table("item_stats").upsert(stats).execute()
        print(f"Upserted stats for item {item['name']}: {stats}")

    units = fetch_units_task()
    traits = fetch_traits_task()
    items = fetch_items_task()

    calculate_unit_stats_task.expand(unit=units)
    calculate_trait_stats_task.expand(trait=traits)
    calculate_item_stats_task.expand(item=items)


calculate_tft_stats()

import json
import httpx

from airflow.sdk import dag, task  # type: ignore
from airflow.providers.google.cloud.hooks.gcs import GCSHook  # type: ignore
from gcs_bucket_api.upload_to_bucket import upload_matches
from datetime import datetime
from db.parse_match_data import parse_match_data
from google import genai
from riot_api.match_api import collect_match_ids, collect_matches
from riot_api.constants import RIOT_REGIONS, HIGH_ELO_TIERS


@dag(
    dag_id="upsert_json_to_bucket_and_db",
    schedule="@daily",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    default_args={"owner": "Astro", "retries": 3},
    tags=["data upsert"],
)
def upsert_json_to_bucket_and_db():

    @task(max_active_tis_per_dagrun=1)
    async def collect_match_ids_task(region: str) -> dict:
        async with httpx.AsyncClient() as async_client:
            match_ids, match_region = await collect_match_ids(
                client=async_client,
                regions=[region],
                tiers=HIGH_ELO_TIERS,
            )
        return {"match_ids": match_ids, "match_region": match_region}

    @task(max_active_tis_per_dagrun=1)
    async def collect_matches_task(collection_result: dict) -> dict:
        import os
        from supabase import create_client
        from db.parse_match_data import filter_new_match_ids

        supabase_client = create_client(
            os.environ["supabase_url"],
            os.environ["supabase_key"],
        )
        # Skip matches a previous run already ingested (the look-back windows overlap)
        new_match_ids = filter_new_match_ids(
            supabase_client, collection_result["match_ids"]
        )
        async with httpx.AsyncClient() as async_client:
            return await collect_matches(
                client=async_client,
                match_ids=new_match_ids,
                match_region=collection_result["match_region"],
            )

    @task
    async def upload_to_gcs_task(match_data: dict) -> None:
        import os

        hook = GCSHook(gcp_conn_id="google_cloud_default")
        storage_client = hook.get_conn()
        async with httpx.AsyncClient() as async_client:
            riot_versions = (
                await async_client.get(
                    "https://ddragon.leagueoflegends.com/api/versions.json"
                )
            ).json()
            await upload_matches(
                match_data=match_data,
                storage_client=storage_client,
                bucket_name=os.environ.get("GCS_BUCKET", "tft-match-data"),
                riot_version=riot_versions[0],
            )

    @task
    async def upsert_players_task() -> None:
        import os
        from supabase import create_client
        from db.upsert_players import upsert_high_elo_players

        supabase_client = create_client(
            os.environ["supabase_url"],
            os.environ["supabase_key"],
        )
        async with httpx.AsyncClient() as async_client:
            for region in RIOT_REGIONS:
                await upsert_high_elo_players(
                    client=async_client,
                    region=region,
                    db_client=supabase_client,
                )

    @task
    async def upsert_to_db_task(matches_data: dict) -> None:
        import os
        from supabase import create_client

        async with httpx.AsyncClient() as async_client:
            riot_versions = (
                await async_client.get(
                    "https://ddragon.leagueoflegends.com/api/versions.json"
                )
            ).json()
            latest_version = riot_versions[0]

        supabase_client = create_client(
            os.environ["supabase_url"],
            os.environ["supabase_key"],
        )
        google_genai_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

        for match_id in matches_data.keys():
            match_data = json.loads(matches_data[match_id])
            print(f"Processing match_id: {match_id}")
            parse_match_data(
                match_data=match_data,
                client=supabase_client,
                latest_version=latest_version,
                google_genai_client=google_genai_client,
            )

    collection_results = collect_match_ids_task.expand(region=RIOT_REGIONS)
    collected_matches = collect_matches_task.expand(
        collection_result=collection_results
    )
    uploaded = upload_to_gcs_task.expand(match_data=collected_matches)
    players_done = upsert_players_task()
    upsert_db = upsert_to_db_task.expand(matches_data=collected_matches)
    [uploaded, players_done] >> upsert_db


upsert_json_to_bucket_and_db()

import asyncio
import json
from google import genai
import httpx

from airflow.sdk import dag, task  # type: ignore
from airflow.providers.amazon.aws.hooks.s3 import S3Hook  # type: ignore
from datetime import datetime
from db.parse_match_data import parse_match_data
from riot_api.match_api import collect_match_ids, fetch_matches
from riot_api.constants import RIOT_REGIONS, HIGH_ELO_TIERS
from b2_bucket_api.upload_to_bucket import upload_matches as upload_matches_to_b2


@dag(
    dag_id="upsert_json_to_b2_bucket",
    schedule="@daily",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    default_args={"owner": "Astro", "retries": 3},
    tags=["data upsert"],
)
def upsert_json_to_b2_bucket():

    @task(max_active_tis_per_dagrun=1)
    def collect_match_ids_task(region: str) -> dict:
        async def _run():
            async with httpx.AsyncClient() as async_client:
                return await collect_match_ids(
                    client=async_client,
                    regions=[region],
                    tiers=HIGH_ELO_TIERS,
                )

        match_ids, match_region = asyncio.run(_run())
        return {"match_ids": match_ids, "match_region": match_region}

    @task(max_active_tis_per_dagrun=1)
    def fetch_matches_task(collection_result: dict) -> dict:
        async def _run():
            async with httpx.AsyncClient() as async_client:
                return await fetch_matches(
                    client=async_client,
                    match_ids=collection_result["match_ids"],
                    match_region=collection_result["match_region"],
                )

        return asyncio.run(_run())

    @task
    def upload_to_b2_task(match_data: dict) -> None:
        hook = S3Hook(aws_conn_id="backblaze_b2")
        s3_client = hook.get_conn()

        async def _run():
            async with httpx.AsyncClient() as async_client:
                riot_versions = (
                    await async_client.get(
                        "https://ddragon.leagueoflegends.com/api/versions.json"
                    )
                ).json()
                latest_version = riot_versions[0]

                await upload_matches_to_b2(
                    match_data=match_data,
                    s3_client=s3_client,
                    bucket_name="tft-match-data",
                    riot_version=latest_version,
                )

        asyncio.run(_run())

    @task
    def upsert_players_task() -> None:
        import os
        from supabase import create_client
        from db.getRiotAPIData import populate_player_table_with_tiered_data

        supabase_client = create_client(
            os.environ["supabase_url"],
            os.environ["supabase_key"],
        )

        async def _run() -> None:
            async with httpx.AsyncClient() as async_client:
                for region in RIOT_REGIONS:
                    await populate_player_table_with_tiered_data(
                        client=async_client,
                        region=region,
                        db_client=supabase_client,
                    )

        asyncio.run(_run())

    @task
    def upsert_to_db_task(matches_data: dict) -> None:
        import os
        from supabase import create_client

        async def _get_latest_version() -> str:
            async with httpx.AsyncClient() as async_client:
                riot_versions = (
                    await async_client.get(
                        "https://ddragon.leagueoflegends.com/api/versions.json"
                    )
                ).json()
                return riot_versions[0]

        latest_version = asyncio.run(_get_latest_version())

        supabase_client = create_client(
            os.environ["supabase_url"],
            os.environ["supabase_key"],
        )

        api_key = os.environ["GEMINI_API_KEY"]
        google_genai_client = genai.Client(api_key=api_key)

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
    fetched = fetch_matches_task.expand(collection_result=collection_results)
    uploaded = upload_to_b2_task.expand(match_data=fetched)
    players_done = upsert_players_task()
    upsert_db = upsert_to_db_task.expand(matches_data=fetched)
    [uploaded, players_done] >> upsert_db


upsert_json_to_b2_bucket()

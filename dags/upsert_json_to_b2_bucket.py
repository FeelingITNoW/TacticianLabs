import asyncio
import httpx

from airflow.sdk import dag, task
from airflow.providers.amazon.aws.hooks.s3 import S3Hook
from datetime import datetime
from riot_api.match_api import collect_match_ids, fetch_matches, upload_matches


# TODO: Make this dag handle changing parameters like regions and tiers based on time
@dag(
    dag_id='upsert_json_to_b2_bucket',
    schedule="@daily",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    default_args={"owner": "Astro", "retries": 3},
)
def upsert_json_to_b2_bucket():

    # TODO: Make regions/tiers configurable via DAG params
    @task
    def collect_match_ids_task() -> dict:
        async def _run():
            async with httpx.AsyncClient() as async_client:
                return await collect_match_ids(
                    client=async_client,
                    regions=["SG2"],
                    tiers=["CHALLENGER"],
                )
        match_ids, match_region = asyncio.run(_run())
        return {"match_ids": match_ids, "match_region": match_region}

    @task
    def fetch_matches_task(collection_result: dict) -> dict:
        async def _run():
            async with httpx.AsyncClient() as async_client:
                return await fetch_matches(
                    client=async_client,
                    match_ids=collection_result["match_ids"],
                    match_region=collection_result["match_region"],
                )
        return asyncio.run(_run())

    # TODO: Include retrieval date in the B2 object key for easy querying
    @task
    def upload_to_b2_task(match_data: dict) -> None:
        hook = S3Hook(aws_conn_id='backblaze_b2')
        s3_client = hook.get_conn()
        upload_matches(
            match_data=match_data,
            s3_client=s3_client,
            bucket_name="tft-match-data",
        )

    upload_to_b2_task(fetch_matches_task(collect_match_ids_task()))


upsert_json_to_b2_bucket()

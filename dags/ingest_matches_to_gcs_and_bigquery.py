import httpx

from airflow.sdk import dag, task  # type: ignore
from airflow.providers.google.cloud.hooks.bigquery import BigQueryHook  # type: ignore
from airflow.providers.google.cloud.hooks.gcs import GCSHook  # type: ignore
from gcs_bucket_api.upload_to_bucket import upload_matches
from datetime import datetime
from db.parse_match_data import write_matches
from google_embedding.embedding_call import make_genai_client
from riot_api.match_api import collect_match_ids, collect_matches
from riot_api.constants import RIOT_REGIONS, HIGH_ELO_TIERS
from riot_api.http_client import get_latest_version

# Matches per BigQuery write: one staging round and one SQL script each
WRITE_CHUNK_SIZE = 50


def _bigquery_client():
    # Same connection and service account as the GCS archive
    return BigQueryHook(gcp_conn_id="google_cloud_default").get_client()


@dag(
    dag_id="ingest_matches_to_gcs_and_bigquery",
    schedule="@daily",
    start_date=datetime(2026, 1, 1),
    catchup=False,
    default_args={"owner": "Astro", "retries": 3},
    tags=["data upsert"],
)
def ingest_matches_to_gcs_and_bigquery():

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
        from db.parse_match_data import filter_new_match_ids

        # Skip matches a previous run already ingested (the look-back windows overlap)
        new_match_ids = filter_new_match_ids(
            _bigquery_client(), collection_result["match_ids"]
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
            riot_version = await get_latest_version(async_client)
        await upload_matches(
            match_data=match_data,
            storage_client=storage_client,
            bucket_name=os.environ.get("GCS_BUCKET", "tft-match-data"),
            riot_version=riot_version,
        )

    @task
    async def upsert_players_task() -> None:
        from db.upsert_players import upsert_high_elo_players

        bigquery_client = _bigquery_client()
        async with httpx.AsyncClient() as async_client:
            for region in RIOT_REGIONS:
                await upsert_high_elo_players(
                    client=async_client,
                    region=region,
                    db_client=bigquery_client,
                )

    @task
    async def upsert_to_bigquery_task(matches_data: dict) -> None:
        async with httpx.AsyncClient() as async_client:
            latest_version = await get_latest_version(async_client)

        bigquery_client = _bigquery_client()
        google_genai_client = make_genai_client()

        match_ids = list(matches_data)
        failed = 0
        for start in range(0, len(match_ids), WRITE_CHUNK_SIZE):
            chunk = {
                match_id: matches_data[match_id]
                for match_id in match_ids[start : start + WRITE_CHUNK_SIZE]
            }
            written, chunk_failed = write_matches(
                bigquery_client, chunk, latest_version, google_genai_client
            )
            failed += chunk_failed
            print(f"Wrote {written} of {len(chunk)} matches")
        if failed:
            raise RuntimeError(f"{failed} matches failed to parse")

    collection_results = collect_match_ids_task.expand(region=RIOT_REGIONS)
    collected_matches = collect_matches_task.expand(
        collection_result=collection_results
    )
    uploaded = upload_to_gcs_task.expand(match_data=collected_matches)
    players_done = upsert_players_task()
    upsert_db = upsert_to_bigquery_task.expand(matches_data=collected_matches)
    [uploaded, players_done] >> upsert_db


ingest_matches_to_gcs_and_bigquery()

"""Cloud Run Job entrypoint: ingest yesterday's high-elo TFT matches.

Run with `python -m jobs.ingest_matches` (PYTHONPATH must include `include/`).

Each Cloud Run task handles one or more routing regions (AMERICAS, EUROPE, ASIA,
SEA). Riot rate limits apply per routing value, so the parallel tasks don't compete.
Set REGIONS=SG2,KR to override the sharding for local runs.
"""

import asyncio
import os
import sys

import httpx
from google import genai
from google.cloud import bigquery, storage

from db.bq import make_client
from db.parse_match_data import filter_new_match_ids, write_matches
from db.upsert_players import upsert_high_elo_players
from gcs_bucket_api.upload_to_bucket import upload_matches
from riot_api.constants import (
    HIGH_ELO_TIERS,
    RIOT_REGIONS,
    RIOT_REGIONS_MAP,
)
from riot_api.http_client import get_latest_version
from riot_api.match_api import collect_match_ids, collect_matches

CHUNK_SIZE = 50
DEFAULT_GCS_BUCKET = "tft-match-data"


def routing_groups() -> dict[str, list[str]]:
    """Platforms in RIOT_REGIONS grouped by routing region, in a stable order."""
    groups: dict[str, list[str]] = {}
    for platform in RIOT_REGIONS:
        groups.setdefault(RIOT_REGIONS_MAP[platform], []).append(platform)
    return dict(sorted(groups.items()))


def groups_for_task(task_index: int, task_count: int) -> dict[str, list[str]]:
    """The routing groups this Cloud Run task is responsible for."""
    items = list(routing_groups().items())
    return dict(items[task_index::task_count])


def groups_from_env() -> dict[str, list[str]]:
    override = os.getenv("REGIONS")
    if override:
        groups: dict[str, list[str]] = {}
        for platform in (p.strip().upper() for p in override.split(",") if p.strip()):
            if platform not in RIOT_REGIONS:
                raise ValueError(f"Unknown region {platform!r}. Valid: {RIOT_REGIONS}")
            groups.setdefault(RIOT_REGIONS_MAP[platform], []).append(platform)
        return groups
    return groups_for_task(
        int(os.getenv("CLOUD_RUN_TASK_INDEX", "0")),
        int(os.getenv("CLOUD_RUN_TASK_COUNT", "1")),
    )


def make_storage_client():
    if os.getenv("SKIP_GCS_UPLOAD") == "1":
        return None
    # Uses Application Default Credentials: the runner service account in
    # Cloud Run, or GOOGLE_APPLICATION_CREDENTIALS / `gcloud auth application-default
    # login` locally.
    return storage.Client()


async def ingest_routing_group(
    http_client: httpx.AsyncClient,
    db_client: bigquery.Client,
    genai_client: genai.Client,
    storage_client,
    routing: str,
    platforms: list[str],
    latest_version: str,
    max_matches: int | None,
) -> int:
    """Ingest one routing region. Returns the number of failures."""
    failures = 0
    for platform in platforms:
        try:
            await upsert_high_elo_players(http_client, platform, db_client)
        except Exception as exc:
            failures += 1
            print(f"[{routing}] player upsert failed for {platform}: {exc!r}")

    match_ids, _ = await collect_match_ids(
        client=http_client, regions=platforms, tiers=HIGH_ELO_TIERS
    )
    new_match_ids = filter_new_match_ids(db_client, match_ids)
    if max_matches is not None:
        new_match_ids = new_match_ids[:max_matches]
    print(
        f"[{routing}] {len(new_match_ids)} new of {len(match_ids)} collected match IDs"
    )

    ingested = 0
    bucket = os.getenv("GCS_BUCKET", DEFAULT_GCS_BUCKET)
    for start in range(0, len(new_match_ids), CHUNK_SIZE):
        chunk = new_match_ids[start : start + CHUNK_SIZE]
        try:
            matches = await collect_matches(http_client, chunk, routing)
        except Exception as exc:
            failures += len(chunk)
            print(f"[{routing}] fetching chunk of {len(chunk)} matches failed: {exc!r}")
            continue

        if storage_client is not None:
            await upload_matches(matches, storage_client, bucket, latest_version)

        try:
            written, failed = write_matches(
                db_client, matches, latest_version, genai_client
            )
        except Exception as exc:
            failures += len(matches)
            print(f"[{routing}] writing chunk of {len(matches)} matches failed: {exc!r}")
            continue
        ingested += written
        failures += failed

    print(f"[{routing}] ingested {ingested} matches, {failures} failures")
    return failures


async def main() -> int:
    groups = groups_from_env()
    if not groups:
        print("No routing regions assigned to this task, nothing to do.")
        return 0
    print(f"Assigned routing groups: {groups}")

    max_matches = int(os.environ["MAX_MATCHES"]) if os.getenv("MAX_MATCHES") else None
    db_client = make_client()
    genai_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    storage_client = make_storage_client()

    failures = 0
    async with httpx.AsyncClient() as http_client:
        latest_version = await get_latest_version(http_client)
        for routing, platforms in groups.items():
            failures += await ingest_routing_group(
                http_client,
                db_client,
                genai_client,
                storage_client,
                routing,
                platforms,
                latest_version,
                max_matches,
            )
    return failures


if __name__ == "__main__":
    total_failures = asyncio.run(main())
    # Non-zero exit makes Cloud Run mark the task failed and retry it
    sys.exit(1 if total_failures else 0)

"""Cloud Run Job entrypoint: ingest yesterday's high-elo TFT matches.

Ranked games are recorded from any tier, normal games only from Challengers, and
other modes never. Rejected match IDs are remembered so they are not fetched again.

Run with `python -m jobs.ingest_matches` (PYTHONPATH must include `include/`).

Per routing region the crawl takes every Challenger, then every Grandmaster, then Masters
(round-robin by LP rank across the region's platforms) until ROUTING_MATCH_TARGET new
matches are found; see riot_api.match_api.collect_match_ids.

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
from db.parse_match_data import (
    filter_new_match_ids,
    select_matches,
    write_matches,
    write_rejected_matches,
)
from db.upsert_players import upsert_high_elo_players
from gcs_bucket_api.upload_to_bucket import upload_matches
from google_embedding.embedding_call import make_genai_client
from riot_api.constants import (
    HIGH_ELO_TIERS,
    INGEST_QUEUES,
    RIOT_REGIONS,
    RIOT_REGIONS_MAP,
    routing_groups,
)
from riot_api.http_client import get_latest_version
from riot_api.match_api import collect_match_ids, collect_matches

# Matches per Riot fetch round (also the unit of GCS upload and rejected-match caching)
FETCH_CHUNK_SIZE = 50
# Matches per BigQuery write. Each write MERGEs into every *_totals table; if any of its
# matches was stored before, those MERGEs read whole played_at partitions of the match
# tables to subtract the replaced rows, so their cost grows with the number of writes,
# not with the matches in each one
WRITE_BATCH_SIZE = 500
DEFAULT_GCS_BUCKET = "tft-match-data"


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
    genai_client: genai.Client | None,
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

    # filter_new drops matches already stored and ones rejected on an earlier run, so
    # only new ones count toward the target and no request is spent fetching the rest
    sources, _ = await collect_match_ids(
        client=http_client,
        regions=platforms,
        tiers=HIGH_ELO_TIERS,
        filter_new=lambda ids: filter_new_match_ids(db_client, ids),
    )
    # Highest-priority tiers first
    new_match_ids = list(sources)
    if max_matches is not None:
        new_match_ids = new_match_ids[:max_matches]
    print(f"[{routing}] {len(new_match_ids)} new match IDs to fetch")

    ingested = rejected_count = 0
    bucket = os.getenv("GCS_BUCKET", DEFAULT_GCS_BUCKET)
    pending: dict[str, dict] = {}

    def flush() -> None:
        nonlocal ingested, failures
        if not pending:
            return
        try:
            written, failed = write_matches(
                db_client, dict(pending), latest_version, genai_client, INGEST_QUEUES
            )
        except Exception as exc:
            # Not stored, so the next run finds and fetches these matches again
            failures += len(pending)
            print(f"[{routing}] writing batch of {len(pending)} matches failed: {exc!r}")
        else:
            ingested += written
            failures += failed
        pending.clear()

    for start in range(0, len(new_match_ids), FETCH_CHUNK_SIZE):
        chunk = new_match_ids[start : start + FETCH_CHUNK_SIZE]
        try:
            matches = await collect_matches(http_client, chunk, routing)
        except Exception as exc:
            failures += len(chunk)
            print(f"[{routing}] fetching chunk of {len(chunk)} matches failed: {exc!r}")
            continue

        matches, rejected = select_matches(matches, sources)
        rejected_count += len(rejected)
        try:
            write_rejected_matches(db_client, rejected)
        except Exception as exc:
            # Only costs a refetch of these matches next run
            print(f"[{routing}] caching {len(rejected)} rejected matches failed: {exc!r}")

        if storage_client is not None:
            await upload_matches(matches, storage_client, bucket, latest_version)

        pending.update(matches)
        if len(pending) >= WRITE_BATCH_SIZE:
            flush()
    flush()

    print(
        f"[{routing}] ingested {ingested} matches, rejected {rejected_count}, "
        f"{failures} failures"
    )
    return failures


async def main() -> int:
    groups = groups_from_env()
    if not groups:
        print("No routing regions assigned to this task, nothing to do.")
        return 0
    print(f"Assigned routing groups: {groups}")

    max_matches = int(os.environ["MAX_MATCHES"]) if os.getenv("MAX_MATCHES") else None
    db_client = make_client()
    genai_client = make_genai_client()
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

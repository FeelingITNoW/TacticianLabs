import asyncio
import json
import httpx
import sys
import time

from datetime import date, datetime, timedelta
from .constants import RIOT_REGIONS, RANK_TIERS, RIOT_REGIONS_MAP
from .http_client import riot_get, riot_get_with_retry
from .league_api import get_challengers, get_grandmasters, get_masters


def get_unix_timestamp_from_n_days_ago(n: int) -> int:
    target_date = date.today() - timedelta(days=n)
    start_of_day = datetime.combine(target_date, datetime.min.time())
    return int(time.mktime(start_of_day.timetuple()))


async def validate_match_retrieval_args(regions: list[str], tiers: list[str]) -> None:
    invalid_regions = [r for r in regions if r not in RIOT_REGIONS]
    if invalid_regions:
        raise ValueError(f"Invalid regions: {invalid_regions}. Valid options are: {RIOT_REGIONS}")

    invalid_tiers = [t for t in tiers if t not in RANK_TIERS]
    if invalid_tiers:
        raise ValueError(f"Invalid tiers: {invalid_tiers}. Valid options are: {RANK_TIERS}")


async def get_match_history_from_last_n_days(
    client: httpx.AsyncClient,
    puuid: str,
    startTime: int,
    region: str,
    start_index: int = 0,
    count: int = 100,
) -> list[str]:
    url = f"https://{region}.api.riotgames.com/tft/match/v1/matches/by-puuid/{puuid}/ids?"
    params = {"startTime": startTime, "count": count}
    response = await riot_get(client, url=url, params=params)
    return response.json()


async def collect_match_ids(
    client: httpx.AsyncClient, regions: list[str], tiers: list[str]
) -> tuple[list[str], str]:
    """Phase 1: resolve players for the given regions/tiers and return all unique match IDs
    from the last 24 hours, together with the routing region string needed in Phase 2."""
    await validate_match_retrieval_args(regions, tiers)

    players_to_fetch: list[dict] = []
    match_region_string = ""
    for region in regions:
        match_region_string = RIOT_REGIONS_MAP[region]
        if "CHALLENGER" in tiers:
            players_to_fetch.extend(await get_challengers(client, region))
        if "GRANDMASTER" in tiers:
            players_to_fetch.extend(await get_grandmasters(client, region))
        if "MASTER" in tiers:
            players_to_fetch.extend(await get_masters(client, region))
        print(f"Region {region} - fetched {len(players_to_fetch)} total players from tiers {tiers}")

    new_match_ids: set[str] = set()
    for player in players_to_fetch:
        puuid = player["puuid"]
        print(f"Fetching match history for player (PUUID: {puuid}) in region {match_region_string}...")
        retrieval_start_time = get_unix_timestamp_from_n_days_ago(1)
        match_list = await get_match_history_from_last_n_days(
            client, puuid=puuid, startTime=retrieval_start_time, region=match_region_string
        )
        if "status" in match_list:
            sys.exit(0)
        new_match_ids.update(match_list)

    print(f"Collected {len(new_match_ids)} unique match IDs.")
    return list(new_match_ids), match_region_string


async def fetch_matches(
    client: httpx.AsyncClient,
    match_ids: list[str],
    match_region: str,
) -> dict[str, str]:
    print(f"Fetching {len(match_ids)} matches…")
    semaphore = asyncio.Semaphore(2)
    results: dict[str, str] = {}

    async def _fetch(match_id: str) -> None:
        async with semaphore:
            response = await riot_get_with_retry(
                client,
                url=f"https://{match_region}.api.riotgames.com/tft/match/v1/matches/{match_id}",
            )
            results[match_id] = json.dumps(response.json())
            print(f"Fetched {match_id}")

    await asyncio.gather(*[_fetch(mid) for mid in match_ids])
    return results


def upload_matches(
    match_data: dict[str, str],
    s3_client,
    bucket_name: str,
) -> None:
    print(f"Uploading {len(match_data)} matches to {bucket_name}…")
    for match_id, body in match_data.items():
        s3_client.put_object(
            Bucket=bucket_name,
            Key=f"{match_id}.json",
            Body=body,
            ContentType="application/json",
        )
        print(f"Uploaded {match_id}")

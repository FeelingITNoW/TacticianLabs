import asyncio
import json
import httpx
import time

from datetime import date, datetime, timedelta
from .constants import (
    MASTER_HISTORY_LIMIT,
    VALID_RANK_TIERS,
    RIOT_REGIONS,
    RIOT_REGIONS_MAP,
)
from .http_client import riot_get_with_retry
from .league_api import get_challengers, get_grandmasters, get_masters


def get_unix_timestamp_from_n_days_ago(n: int) -> int:
    target_date = date.today() - timedelta(days=n)
    start_of_day = datetime.combine(target_date, datetime.min.time())
    return int(time.mktime(start_of_day.timetuple()))


async def validate_match_retrieval_args(regions: list[str], tiers: list[str]) -> None:
    invalid_regions = [r for r in regions if r not in RIOT_REGIONS]
    if invalid_regions:
        raise ValueError(
            f"Invalid regions: {invalid_regions}. Valid options are: {RIOT_REGIONS}"
        )

    invalid_tiers = [t for t in tiers if t not in VALID_RANK_TIERS]
    if invalid_tiers:
        raise ValueError(
            f"Invalid tiers: {invalid_tiers}. Valid options are: {VALID_RANK_TIERS}"
        )


async def get_match_history_from_last_n_days(
    client: httpx.AsyncClient,
    puuid: str,
    startTime: int,
    region: str,
    start_index: int = 0,
    count: int = 100,
) -> list[str]:
    url = (
        f"https://{region}.api.riotgames.com/tft/match/v1/matches/by-puuid/{puuid}/ids?"
    )
    params = {"startTime": startTime, "count": count}
    response = await riot_get_with_retry(client, url=url, params=params)
    return response.json()


# Accepts array of regions and tiers to fetch match IDs for. Returns the match IDs
# and the routing region they were fetched from. Each ID maps to the tiers whose
# players had it in their history, which decides which queues may be recorded.
# Only the top MASTER_HISTORY_LIMIT Masters per platform are crawled.
async def collect_match_ids(
    client: httpx.AsyncClient, regions: list[str], tiers: list[str]
) -> tuple[dict[str, list[str]], str]:
    await validate_match_retrieval_args(regions, tiers)

    # Group puuids by their routing region so each player is fetched from the correct endpoint
    players_by_routing: dict[str, dict[str, str]] = {}  # routing -> puuid -> tier
    for region in regions:
        routing = RIOT_REGIONS_MAP[region]
        players = players_by_routing.setdefault(routing, {})
        if "CHALLENGER" in tiers:
            for puuid in await get_challengers(client, region):
                players[puuid] = "CHALLENGER"
        if "GRANDMASTER" in tiers:
            for puuid in await get_grandmasters(client, region):
                players[puuid] = "GRANDMASTER"
        if "MASTER" in tiers:
            for puuid in await get_masters(client, region, MASTER_HISTORY_LIMIT):
                players[puuid] = "MASTER"
        print(
            f"Region {region} (routing: {routing}) - {len(players)} players from tiers {tiers}"
        )

    total_players = sum(len(v) for v in players_by_routing.values())
    print(f"Total unique players to fetch matches for: {total_players}")

    sources: dict[str, set[str]] = {}
    last_routing = ""
    for routing, players in players_by_routing.items():
        last_routing = routing
        for puuid, tier in players.items():
            print(
                f"Fetching match history for player (PUUID: {puuid}) in region {routing}..."
            )
            retrieval_start_time = get_unix_timestamp_from_n_days_ago(1)
            match_list = await get_match_history_from_last_n_days(
                client,
                puuid=puuid,
                startTime=retrieval_start_time,
                region=routing,
            )
            if "status" in match_list:
                raise RuntimeError(
                    f"Riot API returned an error for PUUID {puuid}: {match_list}"
                )
            for match_id in match_list:
                sources.setdefault(match_id, set()).add(tier)

    print(f"Collected {len(sources)} unique match IDs.")
    return {match_id: sorted(found) for match_id, found in sources.items()}, last_routing


async def collect_matches(
    client: httpx.AsyncClient,
    match_ids: list[str],
    match_region: str,
) -> dict[str, str]:
    print(f"Collecting {len(match_ids)} matches…")
    semaphore = asyncio.Semaphore(2)
    results: dict[str, str] = {}

    async def _fetch(match_id: str) -> None:
        async with semaphore:
            response = await riot_get_with_retry(
                client,
                url=f"https://{match_region}.api.riotgames.com/tft/match/v1/matches/{match_id}",
            )
            results[match_id] = json.dumps(response.json())
            print(f"Collected match {match_id}")

    await asyncio.gather(*[_fetch(mid) for mid in match_ids])
    return results

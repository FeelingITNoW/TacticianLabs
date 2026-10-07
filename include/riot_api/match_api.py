import asyncio
import json
import httpx
import time

from collections.abc import Callable
from datetime import date, datetime, timedelta
from itertools import zip_longest
from .constants import (
    MASTER_CRAWL_BATCH,
    ROUTING_MATCH_TARGET,
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


async def _crawl_player(
    client: httpx.AsyncClient,
    puuid: str,
    tier: str,
    routing: str,
    start_time: int,
    sources: dict[str, set[str]],
) -> list[str]:
    """Record the tier against each match in a player's history. Returns the IDs no
    earlier player had."""
    match_list = await get_match_history_from_last_n_days(
        client, puuid=puuid, startTime=start_time, region=routing
    )
    if "status" in match_list:
        raise RuntimeError(f"Riot API returned an error for PUUID {puuid}: {match_list}")
    fresh = []
    for match_id in match_list:
        if match_id not in sources:
            fresh.append(match_id)
        sources.setdefault(match_id, set()).add(tier)
    return fresh


# Accepts array of regions and tiers to fetch match IDs for. Returns the match IDs
# and the routing region they were fetched from. Each ID maps to the tiers whose
# players had it in their history, which decides which queues may be recorded.
#
# Per routing region the crawl runs in priority order: every Challenger, then every
# Grandmaster (always in full), then Masters, round-robin by LP rank across the
# region's platforms, until `target` new matches have been found. `filter_new` drops
# the IDs that are already stored or rejected, so only new ones count toward the
# target and are returned (in priority order). `target=None` crawls every Master.
async def collect_match_ids(
    client: httpx.AsyncClient,
    regions: list[str],
    tiers: list[str],
    target: int | None = ROUTING_MATCH_TARGET,
    filter_new: Callable[[list[str]], list[str]] = list,
) -> tuple[dict[str, list[str]], str]:
    await validate_match_retrieval_args(regions, tiers)

    platforms_by_routing: dict[str, list[str]] = {}
    for region in regions:
        platforms_by_routing.setdefault(RIOT_REGIONS_MAP[region], []).append(region)

    start_time = get_unix_timestamp_from_n_days_ago(1)
    sources: dict[str, set[str]] = {}
    selected: list[str] = []
    last_routing = ""
    for routing, platforms in platforms_by_routing.items():
        last_routing = routing
        routing_selected: list[str] = []
        for tier, get_players in (
            ("CHALLENGER", get_challengers),
            ("GRANDMASTER", get_grandmasters),
        ):
            if tier not in tiers:
                continue
            fresh: list[str] = []
            crawled = 0
            for platform in platforms:
                for puuid in await get_players(client, platform):
                    fresh += await _crawl_player(
                        client, puuid, tier, routing, start_time, sources
                    )
                    crawled += 1
            routing_selected += filter_new(fresh)
            print(
                f"[{routing}] {tier}: crawled {crawled} players, "
                f"{len(routing_selected)} new matches so far"
            )

        if "MASTER" in tiers:
            # The league lists are sorted by LP, so interleaving them crawls the #1
            # Master on every platform, then the #2, and so on
            lists = [await get_masters(client, platform) for platform in platforms]
            masters = [
                puuid
                for ranks in zip_longest(*lists)
                for puuid in ranks
                if puuid is not None
            ]
            limit = None if target is None else max(target, len(routing_selected))
            crawled = 0
            for start in range(0, len(masters), MASTER_CRAWL_BATCH):
                if limit is not None and len(routing_selected) >= limit:
                    break
                fresh = []
                for puuid in masters[start : start + MASTER_CRAWL_BATCH]:
                    fresh += await _crawl_player(
                        client, puuid, "MASTER", routing, start_time, sources
                    )
                    crawled += 1
                routing_selected += filter_new(fresh)
            if limit is not None:
                routing_selected = routing_selected[:limit]
            print(
                f"[{routing}] MASTER: crawled {crawled} of {len(masters)} players, "
                f"{len(routing_selected)} new matches in total"
            )
        selected += routing_selected

    print(f"Collected {len(selected)} new match IDs.")
    return {match_id: sorted(sources[match_id]) for match_id in selected}, last_routing


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

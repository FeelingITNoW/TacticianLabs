import httpx

from .http_client import riot_get_with_retry

# Apex tiers are served by their own list endpoints rather than /entries/{tier}/{division}
_APEX_TIER_PATHS = {
    "CHALLENGER": "challenger",
    "GRANDMASTER": "grandmaster",
    "MASTER": "master",
}


async def get_league_entries(client: httpx.AsyncClient, region: str, tier: str) -> dict:
    """Full league list for an apex tier: top-level `tier` plus `entries`
    (puuid, rank, leaguePoints, wins, losses, hotStreak, ...)."""
    url = f"https://{region}.api.riotgames.com/tft/league/v1/{_APEX_TIER_PATHS[tier]}?queue=RANKED_TFT"
    response = await riot_get_with_retry(client, url=url)
    return response.json()


async def get_challengers(client: httpx.AsyncClient, region: str) -> list[str]:
    league = await get_league_entries(client, region, "CHALLENGER")
    return [player["puuid"] for player in league["entries"]]


async def get_grandmasters(client: httpx.AsyncClient, region: str) -> list[str]:
    league = await get_league_entries(client, region, "GRANDMASTER")
    return [player["puuid"] for player in league["entries"]]


async def get_masters(
    client: httpx.AsyncClient, region: str, limit: int | None = None
) -> list[str]:
    """Master puuids, highest LP first. The list is huge (up to 10k on one platform),
    so `limit` keeps only the top of it."""
    league = await get_league_entries(client, region, "MASTER")
    ranked = sorted(
        league["entries"], key=lambda player: player.get("leaguePoints", 0), reverse=True
    )
    return [player["puuid"] for player in ranked[:limit]]

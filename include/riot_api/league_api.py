import httpx

from .http_client import riot_get_with_retry


async def get_challengers(client: httpx.AsyncClient, region: str) -> list[dict]:
    url = (
        f"https://{region}.api.riotgames.com/tft/league/v1/challenger?queue=RANKED_TFT"
    )
    response = await riot_get_with_retry(client, url=url)
    players = response.json()["entries"]
    challengers = [player["puuid"] for player in players]
    return challengers


async def get_grandmasters(client: httpx.AsyncClient, region: str) -> list[dict]:
    url = (
        f"https://{region}.api.riotgames.com/tft/league/v1/grandmaster?queue=RANKED_TFT"
    )
    response = await riot_get_with_retry(client, url=url)
    players = response.json()["entries"]
    grandmasters = [player["puuid"] for player in players]
    return grandmasters


async def get_masters(client: httpx.AsyncClient, region: str) -> list[dict]:
    url = f"https://{region}.api.riotgames.com/tft/league/v1/master?queue=RANKED_TFT"
    response = await riot_get_with_retry(client, url=url)
    players = response.json()["entries"]
    masters = [player["puuid"] for player in players]
    return masters

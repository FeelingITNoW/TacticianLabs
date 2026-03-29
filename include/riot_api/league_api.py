import httpx

from .http_client import riot_get


async def get_challengers(client: httpx.AsyncClient, region: str) -> list[dict]:
    url = f"https://{region}.api.riotgames.com/tft/league/v1/challenger?queue=RANKED_TFT"
    response = await riot_get(client, url=url)
    return response.json()["entries"]


async def get_grandmasters(client: httpx.AsyncClient, region: str) -> list[dict]:
    url = f"https://{region}.api.riotgames.com/tft/league/v1/grandmaster?queue=RANKED_TFT"
    response = await riot_get(client, url=url)
    return response.json()["entries"]


async def get_masters(client: httpx.AsyncClient, region: str) -> list[dict]:
    url = f"https://{region}.api.riotgames.com/tft/league/v1/master?queue=RANKED_TFT"
    response = await riot_get(client, url=url)
    return response.json()["entries"]

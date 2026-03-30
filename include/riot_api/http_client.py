import asyncio
import httpx

from .constants import RIOT_API_KEY


def _ensure_riot_api_key() -> None:
    if RIOT_API_KEY:
        return
    raise RuntimeError(
        "Riot API key not found. Set RIOT_API_KEY (preferred) or API_KEY in .env"
    )


async def riot_get(
    client: httpx.AsyncClient, url: str, params: dict | None = None
) -> httpx.Response:
    _ensure_riot_api_key()
    request_params = dict(params or {})
    request_params["api_key"] = RIOT_API_KEY
    response = await client.get(url, params=request_params, timeout=30)
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        if response.status_code == 401:
            raise RuntimeError(
                "Riot API returned 401 Unauthorized. Your key is missing, expired, or invalid. "
                "Generate a fresh key at https://developer.riotgames.com/, then update .env with "
                "RIOT_API_KEY=RGAPI-..."
            ) from exc
        raise
    return response


async def riot_get_with_retry(
    client: httpx.AsyncClient,
    url: str,
    params: dict | None = None,
    max_retries: int = 5,
) -> httpx.Response:
    """riot_get with exponential backoff for 429s and transient network errors."""
    delay = 1
    for attempt in range(max_retries):
        try:
            return await riot_get(client, url=url, params=params)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                retry_after = int(exc.response.headers.get("Retry-After", delay))
                print(f"Rate limited. Retrying after {retry_after}s (attempt {attempt + 1}/{max_retries})")
                await asyncio.sleep(retry_after)
                delay = min(delay * 2, 120)
            else:
                raise
        except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError) as exc:
            if attempt < max_retries - 1:
                print(f"Network error, retrying in {delay}s (attempt {attempt + 1}/{max_retries}): {exc}")
                await asyncio.sleep(delay)
                delay = min(delay * 2, 120)
            else:
                raise
    raise RuntimeError(f"All {max_retries} retries exhausted for {url}")

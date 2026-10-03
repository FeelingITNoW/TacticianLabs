import asyncio
import httpx

from .constants import RIOT_API_KEY, RIOT_VERSIONS_URL


def _ensure_riot_api_key() -> None:
    if RIOT_API_KEY:
        return
    raise RuntimeError(
        "Riot API key not found. Set RIOT_API_KEY (preferred) or API_KEY in .env"
    )


# TODO: rename this to something better too much overlap with riot_get_with_retry and it's not just a simple get anymore
# TODO: refactor: no reason to use this over riot_get_with_retry in league_api
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
                print(
                    f"Rate limited. Retrying after {retry_after}s (attempt {attempt + 1}/{max_retries})"
                )
                await asyncio.sleep(retry_after)
                delay = min(delay * 2, 120)
            else:
                raise
        except (httpx.ConnectError, httpx.ReadError, httpx.RemoteProtocolError) as exc:
            if attempt < max_retries - 1:
                print(
                    f"Network error, retrying in {delay}s (attempt {attempt + 1}/{max_retries}): {exc}"
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, 120)
            else:
                raise
    raise RuntimeError(f"All {max_retries} retries exhausted for {url}")


async def get_latest_version(client: httpx.AsyncClient, max_retries: int = 5) -> str:
    """The newest Data Dragon version (e.g. "16.19.1"), retrying timeouts and 5xx.

    Data Dragon is a CDN, not the Riot API: no key, and no 429s to honor.
    """
    delay = 1
    for attempt in range(max_retries):
        try:
            response = await client.get(RIOT_VERSIONS_URL, timeout=30)
            response.raise_for_status()
            return response.json()[0]
        except (httpx.TransportError, httpx.HTTPStatusError) as exc:
            retryable = not isinstance(exc, httpx.HTTPStatusError) or (
                exc.response.status_code >= 500
            )
            if not retryable or attempt == max_retries - 1:
                raise
            print(
                f"Fetching Data Dragon versions failed, retrying in {delay}s "
                f"(attempt {attempt + 1}/{max_retries}): {exc!r}"
            )
            await asyncio.sleep(delay)
            delay = min(delay * 2, 30)
    raise RuntimeError(f"All {max_retries} retries exhausted for {RIOT_VERSIONS_URL}")

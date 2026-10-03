"""Tests for the Data Dragon version lookup (include/riot_api/http_client.py)."""

import httpx
import pytest

from riot_api import http_client
from riot_api.http_client import get_latest_version


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def instant(_):
        return None

    monkeypatch.setattr(http_client.asyncio, "sleep", instant)


def client_for(responses):
    """An AsyncClient that replays `responses` (exceptions are raised) in order."""
    calls = iter(responses)

    def handler(request):
        outcome = next(calls)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


class TestGetLatestVersion:
    async def test_returns_newest_version(self):
        async with client_for([httpx.Response(200, json=["16.19.1", "16.18.1"])]) as c:
            assert await get_latest_version(c) == "16.19.1"

    async def test_retries_timeouts_and_server_errors(self):
        responses = [
            httpx.ConnectTimeout("timed out"),
            httpx.Response(503),
            httpx.Response(200, json=["16.19.1"]),
        ]
        async with client_for(responses) as c:
            assert await get_latest_version(c) == "16.19.1"

    async def test_does_not_retry_client_errors(self):
        async with client_for([httpx.Response(404)]) as c:
            with pytest.raises(httpx.HTTPStatusError):
                await get_latest_version(c)

    async def test_gives_up_after_max_retries(self):
        responses = [httpx.ReadTimeout("timed out")] * 3
        async with client_for(responses) as c:
            with pytest.raises(httpx.ReadTimeout):
                await get_latest_version(c, max_retries=3)

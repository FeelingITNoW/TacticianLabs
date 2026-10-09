"""Tests for the per-player crawl step (include/riot_api/match_api.py)."""

import httpx
import pytest

from riot_api import http_client
from riot_api.match_api import _crawl_player


@pytest.fixture(autouse=True)
def fast_riot(monkeypatch):
    async def instant(_):
        return None

    monkeypatch.setattr(http_client.asyncio, "sleep", instant)
    monkeypatch.setattr(http_client, "RIOT_API_KEY", "RGAPI-test")


def client_for(outcome):
    def handler(request):
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def crawl(client, sources):
    return await _crawl_player(client, "puuid", "MASTER", "AMERICAS", 0, sources)


class TestCrawlPlayer:
    async def test_records_tier_against_matches(self):
        sources = {"NA1_1": {"CHALLENGER"}}
        async with client_for(httpx.Response(200, json=["NA1_1", "NA1_2"])) as c:
            assert await crawl(c, sources) == ["NA1_2"]
        assert sources == {"NA1_1": {"CHALLENGER", "MASTER"}, "NA1_2": {"MASTER"}}

    async def test_skips_player_when_timeouts_persist(self):
        sources = {}
        async with client_for(httpx.ReadTimeout("timed out")) as c:
            assert await crawl(c, sources) == []
        assert sources == {}

    async def test_skips_player_on_persistent_server_error(self):
        async with client_for(httpx.Response(503)) as c:
            assert await crawl(c, {}) == []

    async def test_client_errors_still_raise(self):
        async with client_for(httpx.Response(403)) as c:
            with pytest.raises(httpx.HTTPStatusError):
                await crawl(c, {})

    async def test_unauthorized_still_raises(self):
        async with client_for(httpx.Response(401)) as c:
            with pytest.raises(RuntimeError, match="401"):
                await crawl(c, {})

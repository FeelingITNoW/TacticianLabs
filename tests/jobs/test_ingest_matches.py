"""Tests for the Cloud Run Job entrypoint (include/jobs/ingest_matches.py)."""

import pytest

from google_embedding.embedding_call import make_genai_client
from jobs.ingest_matches import groups_for_task, groups_from_env, routing_groups
from riot_api.constants import RIOT_REGIONS, RIOT_REGIONS_MAP


class TestSharding:
    def test_routing_groups_use_the_platform_map(self):
        for routing, platforms in routing_groups().items():
            assert all(RIOT_REGIONS_MAP[p] == routing for p in platforms)

    @pytest.mark.parametrize("task_count", [1, 2, 3, 4, 6])
    def test_every_platform_is_handled_exactly_once(self, task_count):
        seen: list[str] = []
        for index in range(task_count):
            for platforms in groups_for_task(index, task_count).values():
                seen.extend(platforms)
        assert sorted(seen) == sorted(RIOT_REGIONS)

    def test_four_tasks_get_one_routing_region_each(self):
        assert [len(groups_for_task(i, 4)) for i in range(4)] == [1, 1, 1, 1]

    def test_regions_env_overrides_task_index(self, monkeypatch):
        monkeypatch.setenv("REGIONS", "sg2, kr")
        monkeypatch.setenv("CLOUD_RUN_TASK_INDEX", "3")
        monkeypatch.setenv("CLOUD_RUN_TASK_COUNT", "4")
        assert groups_from_env() == {"SEA": ["SG2"], "ASIA": ["KR"]}

    def test_unknown_region_in_env_raises(self, monkeypatch):
        monkeypatch.setenv("REGIONS", "MARS1")
        with pytest.raises(ValueError, match="MARS1"):
            groups_from_env()


class TestEmbeddingSwitch:
    def test_skip_embeddings_means_no_client_and_no_api_key(self, monkeypatch):
        monkeypatch.setenv("SKIP_EMBEDDINGS", "1")
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)

        assert make_genai_client() is None

    def test_embeddings_are_on_by_default(self, monkeypatch):
        monkeypatch.delenv("SKIP_EMBEDDINGS", raising=False)
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")

        assert make_genai_client() is not None

    def test_other_values_keep_embeddings_on(self, monkeypatch):
        monkeypatch.setenv("SKIP_EMBEDDINGS", "0")
        monkeypatch.setenv("GEMINI_API_KEY", "test-key")

        assert make_genai_client() is not None

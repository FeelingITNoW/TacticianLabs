"""Tests for the GCS -> BigQuery loader (include/jobs/load_gcs_matches.py)."""

import copy
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from jobs.load_gcs_matches import DEFAULT_PREFIX, load_prefix, parse_prefix
from tests.conftest import FakeBigQuery
from tests.dags.test_constants import MATCH_DATA_RANKED_GAME

PREFIX = "tft/matches/16.19.1/2026-09-28/"


def _blob(match_id: str):
    body = copy.deepcopy(MATCH_DATA_RANKED_GAME)
    body["metadata"]["match_id"] = match_id
    return SimpleNamespace(
        name=f"{PREFIX}{match_id}.json", download_as_text=lambda: json.dumps(body)
    )


def _storage(count: int):
    storage = MagicMock()
    storage.list_blobs.return_value = [_blob(f"SG2_{i:04d}") for i in range(count)]
    return storage


def _load(fake_bq, storage, genai_client=None, **kwargs):
    with patch(
        "db.parse_match_data.get_embeddings",
        side_effect=lambda client, comps: [[0.1] * 768 for _ in comps],
    ) as mock_embed:
        result = load_prefix(
            fake_bq, storage, genai_client, "bucket", prefix=PREFIX, **kwargs
        )
    return result, mock_embed


class TestParsePrefix:
    def test_default_prefix_is_the_september_28_archive(self):
        assert parse_prefix(DEFAULT_PREFIX) == ("16.19.1", "2026-09-28")

    @pytest.mark.parametrize(
        "bad", ["", "tft/matches/16.19.1/", "tft/matches/16.19.1/2026-09-28", "x/y/z/"]
    )
    def test_rejects_other_shapes(self, bad):
        with pytest.raises(ValueError):
            parse_prefix(bad)


class TestLoadPrefix:
    def test_loads_in_chunks_with_the_archive_version(self, fake_bq):
        (ingested, failed), _ = _load(fake_bq, _storage(120), genai_client=MagicMock())

        assert (ingested, failed) == (120, 0)
        # one existence check, then one write script per 50 matches
        write_scripts = [q for q, _ in fake_bq.queries if "INSERT INTO" in q]
        assert len(write_scripts) == 3
        assert {r["game_version"] for r in fake_bq.staged("matches")} == {"16.19.1"}

    def test_skips_matches_already_loaded(self):
        fake_bq = FakeBigQuery(query_rows=[{"match_id": "SG2_0000"}])

        (ingested, _), _ = _load(fake_bq, _storage(3))

        assert ingested == 2
        assert "SG2_0000" not in {r["match_id"] for r in fake_bq.staged("matches")}

    def test_reload_ignores_what_is_already_loaded(self):
        fake_bq = FakeBigQuery(query_rows=[{"match_id": "SG2_0000"}])

        (ingested, _), _ = _load(fake_bq, _storage(3), reload=True)

        assert ingested == 3

    def test_limit(self, fake_bq):
        (ingested, _), _ = _load(fake_bq, _storage(10), limit=4)

        assert ingested == 4

    def test_embeds_only_with_a_genai_client(self, fake_bq):
        _, without = _load(fake_bq, _storage(2), genai_client=None)
        _, with_client = _load(FakeBigQuery(), _storage(2), genai_client=MagicMock())

        assert without.call_count == 0
        assert with_client.call_count == 2

    def test_a_failing_download_fails_its_chunk_and_the_load_continues(self, fake_bq):
        storage = _storage(60)

        def broken():
            raise OSError("boom")

        storage.list_blobs.return_value[0].download_as_text = broken

        (ingested, failed), _ = _load(fake_bq, storage)

        assert (ingested, failed) == (10, 50)

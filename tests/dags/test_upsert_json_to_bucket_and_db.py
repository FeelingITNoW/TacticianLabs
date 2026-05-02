"""
Tests for the upsert_json_to_b2_bucket DAG and the individual helper functions it calls.

Structure
---------
TestDagStructure          – structural/metadata checks via DagBag
TestValidateMatchArgs     – riot_api.match_api.validate_match_retrieval_args
TestCollectMatchIds       – riot_api.match_api.collect_match_ids
TestFetchMatches          – riot_api.match_api.collect_matches
TestUploadToBucket        – b2_bucket_api.upload_to_bucket.upload_matches
TestParseMatchData        – db.parse_match_data.parse_match_data
TestPopulatePlayerTable   – db.getRiotAPIData.populate_player_table_with_tiered_data
"""

import pytest
import httpx

from unittest.mock import MagicMock, patch
from airflow.models import DagBag  # type: ignore
from riot_api.match_api import collect_match_ids
from tests.dags.test_constants import MATCH_DATA_RANKED_GAME, MATCH_DATA_UNRANKED_GAME


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_participant(puuid: str = "puuid-1", placement: int = 1) -> dict:
    return {
        "puuid": puuid,
        "placement": placement,
        "level": 8,
        "gold_left": 2,
        "last_round": 30,
        "total_damage_to_players": 100,
        "traits": [
            {
                "name": "Set10_Punk",
                "tier_current": 2,
                "num_units": 4,
                "style": 2,
                "tier_total": 3,
            }
        ],
        "units": [
            {
                "character_id": "TFT10_Jinx",
                "tier": 2,
                "itemNames": ["TFT_Item_RabadonsDeathcap"],
                "rarity": 2,
            }
        ],
    }


def make_match_data_ranked_game():
    return MATCH_DATA_RANKED_GAME


def make_match_data_unranked_game():
    return MATCH_DATA_UNRANKED_GAME


# ---------------------------------------------------------------------------
# DAG structural tests
# ---------------------------------------------------------------------------


class TestDagStructure:
    def setup_method(self):
        self.dag_bag = DagBag(include_examples=False)
        self.dag = self.dag_bag.get_dag("upsert_json_to_bucket_and_db")

    def test_dag_loads_without_import_errors(self):
        assert not self.dag_bag.import_errors, (
            f"Import errors: {self.dag_bag.import_errors}"
        )

    def test_dag_exists(self):
        assert self.dag is not None, "upsert_json_to_bucket_and_db not found in DagBag"

    def test_dag_id(self):
        assert self.dag.dag_id == "upsert_json_to_bucket_and_db"

    def test_dag_catchup_disabled(self):
        assert self.dag.catchup is False

    def test_dag_has_tags(self):
        assert self.dag.tags, "DAG must declare at least one tag"

    def test_dag_has_retries_in_default_args(self):
        retries = self.dag.default_args.get("retries", 0)
        assert retries > 0, "default_args should set retries > 0"

    def test_dag_has_expected_tasks(self):
        task_ids = {t.task_id for t in self.dag.tasks}
        for expected in (
            "collect_match_ids_task",
            "collect_matches_task",
            "upload_to_b2_task",
            "upsert_players_task",
            "upsert_to_db_task",
        ):
            assert any(expected in tid for tid in task_ids), (
                f"Expected task '{expected}' not found. Tasks: {task_ids}"
            )

    def test_upsert_to_db_task_depends_on_upload_and_players(self):
        # upsert_to_db_task must run after both upload_to_b2_task and upsert_players_task
        task_ids = {t.task_id for t in self.dag.tasks}
        upsert_db_id = next(tid for tid in task_ids if "upsert_to_db" in tid)
        upsert_db_task = self.dag.get_task(upsert_db_id)
        upstream_ids = {t.task_id for t in upsert_db_task.upstream_list}
        assert any("upload_to_b2" in uid for uid in upstream_ids), (
            "upsert_to_db_task must be downstream of upload_to_b2_task"
        )
        assert any("upsert_players" in uid for uid in upstream_ids), (
            "upsert_to_db_task must be downstream of upsert_players_task"
        )


# ---------------------------------------------------------------------------
# validate_match_retrieval_args
# ---------------------------------------------------------------------------


class TestValidateMatchArgs:
    async def test_valid_args_do_not_raise(self):
        from riot_api.match_api import validate_match_retrieval_args

        await validate_match_retrieval_args(regions=["SG2"], tiers=["CHALLENGER"])

    async def test_invalid_region_raises_value_error(self):
        from riot_api.match_api import validate_match_retrieval_args

        with pytest.raises(ValueError, match="Invalid regions"):
            await validate_match_retrieval_args(
                regions=["INVALID"], tiers=["CHALLENGER"]
            )

    async def test_invalid_tier_raises_value_error(self):
        from riot_api.match_api import validate_match_retrieval_args

        with pytest.raises(ValueError, match="Invalid tiers"):
            await validate_match_retrieval_args(regions=["SG2"], tiers=["MYTHIC"])

    async def test_multiple_invalid_regions_listed_in_error(self):
        from riot_api.match_api import validate_match_retrieval_args

        with pytest.raises(ValueError) as exc_info:
            await validate_match_retrieval_args(
                regions=["BAD1", "BAD2"], tiers=["CHALLENGER"]
            )
        assert "BAD1" in str(exc_info.value)
        assert "BAD2" in str(exc_info.value)


# ---------------------------------------------------------------------------
# collect_matches
# ---------------------------------------------------------------------------


class TestCollectMatchIds:
    @pytest.mark.integration
    async def test_handles_single_region(self):
        async with httpx.AsyncClient() as async_client:
            result = await collect_match_ids(
                client=async_client, regions=["SG2"], tiers=["CHALLENGER"]
            )
        BR_match_ids = [
            match_id for match_id in result[0] if match_id.startswith("BR1")
        ]
        SG2_match_ids = [
            match_id for match_id in result[0] if match_id.startswith("SG2")
        ]
        assert BR_match_ids == [], "Expected no BR1 match IDs"
        assert SG2_match_ids, "Expected some SG2 match IDs"

    @pytest.mark.integration
    async def test_handles_multiple_regions(self):
        async with httpx.AsyncClient() as async_client:
            result = await collect_match_ids(
                client=async_client, regions=["SG2", "BR1"], tiers=["CHALLENGER"]
            )
        BR_match_ids = [
            match_id for match_id in result[0] if match_id.startswith("BR1")
        ]
        SG2_match_ids = [
            match_id for match_id in result[0] if match_id.startswith("SG2")
        ]
        assert BR_match_ids, "Expected some BR1 match IDs"
        assert SG2_match_ids, "Expected some SG2 match IDs"

    @pytest.mark.integration
    async def test_invalid_args_raise_value_error(self):
        async with httpx.AsyncClient() as async_client:
            with pytest.raises(ValueError):
                await collect_match_ids(
                    client=async_client, regions=["INVALID"], tiers=["CHALLENGER"]
                )
            with pytest.raises(ValueError):
                await collect_match_ids(
                    client=async_client, regions=["SG2"], tiers=["MYTHIC"]
                )


# ---------------------------------------------------------------------------
# parse_match_data
# ---------------------------------------------------------------------------


class TestParseMatchData:
    def _make_mock_client(self):
        mock_client = MagicMock()
        mock_client.table.return_value.upsert.return_value.execute.return_value = (
            MagicMock()
        )
        mock_client.table.return_value.insert.return_value.execute.return_value = (
            MagicMock()
        )
        return mock_client

    def test_skips_non_ranked_match(self):
        mock_client = self._make_mock_client()
        match_data = make_match_data_unranked_game()

        with patch("db.parse_match_data.get_embedding", return_value=[0.1] * 768):
            from db.parse_match_data import parse_match_data

            results = parse_match_data(
                match_data=match_data,
                client=mock_client,
                latest_version="14.1.1",
                google_genai_client=MagicMock(),
            )

        assert results is None, "Expected no database calls for unranked match"

    def test_inserts_match_row_for_ranked_match(self):
        mock_client = self._make_mock_client()
        match_data = make_match_data_ranked_game()

        with patch("db.parse_match_data.get_embedding", return_value=[0.1] * 768):
            from db.parse_match_data import parse_match_data

            parse_match_data(
                match_data=match_data,
                client=mock_client,
                latest_version="14.1.1",
                google_genai_client=MagicMock(),
            )

        table_calls = [c.args[0] for c in mock_client.table.call_args_list]
        assert "matches" in table_calls

    def test_inserts_participant_rows(self):
        mock_client = self._make_mock_client()
        match_data = make_match_data_ranked_game()

        with patch("db.parse_match_data.get_embedding", return_value=[0.1] * 768):
            from db.parse_match_data import parse_match_data

            results = parse_match_data(
                match_data=match_data,
                client=mock_client,
                latest_version="14.1.1",
                google_genai_client=MagicMock(),
            )

        assert results["match_table_entry"], "Expected match table entry to be returned"
        assert results["participant_rows"], "Expected participant rows to be returned"
        assert results["trait_rows"], "Expected trait rows to be returned"
        assert results["unit_rows"], "Expected unit rows to be returned"

    def test_participants_are_not_duplicated(self):
        mock_client = self._make_mock_client()
        match_data = make_match_data_ranked_game()

        with patch("db.parse_match_data.get_embedding", return_value=[0.1] * 768):
            from db.parse_match_data import parse_match_data

            results = parse_match_data(
                match_data=match_data,
                client=mock_client,
                latest_version="14.1.1",
                google_genai_client=MagicMock(),
            )

        participants = results["participant_rows"]
        assert len(participants) == len(set(p["puuid"] for p in participants)), (
            "Expected no duplicate participants"
        )

    def test_calls_get_embedding_once_per_participant(self):
        match_data = make_match_data_ranked_game()
        mock_client = self._make_mock_client()

        with patch(
            "db.parse_match_data.get_embedding", return_value=[0.1] * 768
        ) as mock_embed:
            from db.parse_match_data import parse_match_data

            parse_match_data(
                match_data=match_data,
                client=mock_client,
                latest_version="14.1.1",
                google_genai_client=MagicMock(),
            )

        assert mock_embed.call_count == len(match_data["info"]["participants"])

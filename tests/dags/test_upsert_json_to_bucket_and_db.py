"""
Tests for the upsert_json_to_bucket_and_db DAG and the individual helper functions it calls.

Structure
---------
TestDagStructure          – structural/metadata checks via DagBag
TestValidateMatchArgs     – riot_api.match_api.validate_match_retrieval_args
TestCollectMatchIds       – riot_api.match_api.collect_match_ids
TestFetchMatches          – riot_api.match_api.collect_matches
TestUploadToBucket        – gcs_bucket_api.upload_to_bucket.upload_matches
TestParseMatchData        – db.parse_match_data.parse_match_data
TestUpsertHighEloPlayers  – db.upsert_players.upsert_high_elo_players
TestFilterNewMatchIds     – db.parse_match_data.filter_new_match_ids
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


def _fake_embeddings(client, compositions):
    return [[0.1] * 768 for _ in compositions]


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
            "upload_to_gcs_task",
            "upsert_players_task",
            "upsert_to_db_task",
        ):
            assert any(expected in tid for tid in task_ids), (
                f"Expected task '{expected}' not found. Tasks: {task_ids}"
            )

    def test_upsert_to_db_task_depends_on_upload_and_players(self):
        # upsert_to_db_task must run after both upload_to_gcs_task and upsert_players_task
        task_ids = {t.task_id for t in self.dag.tasks}
        upsert_db_id = next(tid for tid in task_ids if "upsert_to_db" in tid)
        upsert_db_task = self.dag.get_task(upsert_db_id)
        upstream_ids = {t.task_id for t in upsert_db_task.upstream_list}
        assert any("upload_to_gcs" in uid for uid in upstream_ids), (
            "upsert_to_db_task must be downstream of upload_to_gcs_task"
        )
        assert any("upsert_players" in uid for uid in upstream_ids), (
            "upsert_to_db_task must be downstream of upsert_players_task"
        )


# ---------------------------------------------------------------------------
# upload_matches
# ---------------------------------------------------------------------------


class TestUploadToBucket:
    async def test_uploads_each_match_under_the_expected_key(self):
        from gcs_bucket_api.upload_to_bucket import upload_matches

        mock_storage_client = MagicMock()
        mock_bucket = mock_storage_client.bucket.return_value
        mock_blob = mock_bucket.blob.return_value

        await upload_matches(
            match_data={"NA1_1": '{"foo": "bar"}'},
            storage_client=mock_storage_client,
            bucket_name="tft-match-data",
            riot_version="14.1.1",
        )

        mock_storage_client.bucket.assert_called_once_with("tft-match-data")
        (blob_name,), _ = mock_bucket.blob.call_args
        assert blob_name.startswith("tft/matches/14.1.1/")
        assert blob_name.endswith("/NA1_1.json")
        mock_blob.upload_from_string.assert_called_once_with(
            '{"foo": "bar"}', content_type="application/json"
        )

    async def test_uploads_one_blob_per_match(self):
        from gcs_bucket_api.upload_to_bucket import upload_matches

        mock_storage_client = MagicMock()

        await upload_matches(
            match_data={"NA1_1": "{}", "NA1_2": "{}", "NA1_3": "{}"},
            storage_client=mock_storage_client,
            bucket_name="tft-match-data",
            riot_version="14.1.1",
        )

        assert mock_storage_client.bucket.return_value.blob.call_count == 3


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

        with patch("db.parse_match_data.get_embeddings", side_effect=_fake_embeddings):
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

        with patch("db.parse_match_data.get_embeddings", side_effect=_fake_embeddings):
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

        with patch("db.parse_match_data.get_embeddings", side_effect=_fake_embeddings):
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

        with patch("db.parse_match_data.get_embeddings", side_effect=_fake_embeddings):
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

    def _parse(self, mock_client):
        with patch(
            "db.parse_match_data.get_embeddings", side_effect=_fake_embeddings
        ) as mock_embed:
            from db.parse_match_data import parse_match_data

            results = parse_match_data(
                match_data=make_match_data_ranked_game(),
                client=mock_client,
                latest_version="14.1.1",
                google_genai_client=MagicMock(),
            )
        return results, mock_embed

    def test_embeds_all_participants_in_one_call(self):
        match_data = make_match_data_ranked_game()
        results, mock_embed = self._parse(self._make_mock_client())

        assert mock_embed.call_count == 1
        compositions = mock_embed.call_args.args[1]
        assert len(compositions) == len(match_data["info"]["participants"])
        assert all(len(row["embedding"]) == 768 for row in results["participant_rows"])

    def test_upserts_players_for_every_participant_before_participants(self):
        mock_client = self._make_mock_client()
        results, _ = self._parse(mock_client)

        match_data = make_match_data_ranked_game()
        platform = match_data["metadata"]["match_id"].split("_")[0]
        player_rows = results["player_rows"]
        assert {r["puuid"] for r in player_rows} == {
            p["puuid"] for p in match_data["info"]["participants"]
        }
        assert all(r["region"] == platform for r in player_rows)
        assert all(r["game_name"] for r in player_rows)

        # participants.puuid has an FK to players, so players must be written first
        table_calls = [c.args[0] for c in mock_client.table.call_args_list]
        assert table_calls.index("players") < table_calls.index("participants")

    def test_participants_and_traits_are_upserted_not_inserted(self):
        mock_client = self._make_mock_client()
        self._parse(mock_client)

        upserts = mock_client.table.return_value.upsert.call_args_list
        conflicts = {c.kwargs.get("on_conflict") for c in upserts}
        assert "match_id,puuid" in conflicts
        assert "match_id,puuid,name" in conflicts

    def test_units_for_match_are_replaced(self):
        mock_client = self._make_mock_client()
        self._parse(mock_client)

        match_id = make_match_data_ranked_game()["metadata"]["match_id"]
        mock_client.table.return_value.delete.return_value.eq.assert_called_with(
            "match_id", match_id
        )
        assert mock_client.table.return_value.insert.called


# ---------------------------------------------------------------------------
# filter_new_match_ids
# ---------------------------------------------------------------------------


class TestFilterNewMatchIds:
    def test_drops_ids_already_in_matches(self):
        from db.parse_match_data import filter_new_match_ids

        mock_client = MagicMock()
        select = mock_client.table.return_value.select.return_value
        select.in_.return_value.execute.return_value = MagicMock(
            data=[{"match_id": "NA1_2"}]
        )

        result = filter_new_match_ids(mock_client, ["NA1_1", "NA1_2", "NA1_3"])

        assert result == ["NA1_1", "NA1_3"]
        mock_client.table.assert_called_with("matches")

    def test_queries_in_chunks(self):
        from db.parse_match_data import filter_new_match_ids

        mock_client = MagicMock()
        select = mock_client.table.return_value.select.return_value
        select.in_.return_value.execute.return_value = MagicMock(data=[])

        ids = [f"KR_{i}" for i in range(250)]
        assert filter_new_match_ids(mock_client, ids, chunk_size=100) == ids
        assert select.in_.call_count == 3


# ---------------------------------------------------------------------------
# upsert_high_elo_players
# ---------------------------------------------------------------------------


class TestUpsertHighEloPlayers:
    LEAGUE = {
        "tier": "CHALLENGER",
        "entries": [
            {
                "puuid": "p1",
                "rank": "I",
                "leaguePoints": 1200,
                "wins": 50,
                "losses": 40,
                "hotStreak": True,
            },
            {"puuid": "p2", "rank": "I", "leaguePoints": 900, "wins": 30, "losses": 35},
        ],
    }

    def test_build_player_rows_maps_league_entries(self):
        from db.upsert_players import build_player_rows

        players, stats = build_player_rows(self.LEAGUE, "OC1")

        assert players == [
            {"puuid": "p1", "region": "OC1"},
            {"puuid": "p2", "region": "OC1"},
        ]
        assert stats[0] == {
            "puuid": "p1",
            "tier": "CHALLENGER",
            "rank": "I",
            "league_points": 1200,
            "wins": 50,
            "losses": 40,
            "hot_streak": True,
        }
        assert stats[1]["hot_streak"] is False

    async def test_one_riot_call_per_tier(self):
        from db.upsert_players import upsert_high_elo_players

        mock_db = MagicMock()
        with patch(
            "db.upsert_players.get_league_entries", return_value=self.LEAGUE
        ) as mock_league:
            written = await upsert_high_elo_players(
                MagicMock(), "OC1", mock_db, tiers=["CHALLENGER", "GRANDMASTER"]
            )

        assert mock_league.call_count == 2
        assert written == 4
        table_calls = [c.args[0] for c in mock_db.table.call_args_list]
        assert table_calls == [
            "players",
            "player_ranked_stats",
            "players",
            "player_ranked_stats",
        ]

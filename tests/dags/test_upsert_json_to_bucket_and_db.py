"""
Tests for the upsert_json_to_bucket_and_db DAG and the individual helper functions it calls.

Structure
---------
TestDagStructure          – structural/metadata checks via DagBag
TestValidateMatchArgs     – riot_api.match_api.validate_match_retrieval_args
TestCollectMatchIds       – riot_api.match_api.collect_match_ids
TestFetchMatches          – riot_api.match_api.collect_matches
TestUploadToBucket        – gcs_bucket_api.upload_to_bucket.upload_matches
TestBuildMatchRows        – db.parse_match_data.build_match_rows
TestWriteMatches          – db.parse_match_data.write_matches (against FakeBigQuery)
TestFilterNewMatchIds     – db.parse_match_data.filter_new_match_ids
TestUpsertHighEloPlayers  – db.upsert_players.upsert_high_elo_players
"""

import json

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
# build_match_rows / write_matches
# ---------------------------------------------------------------------------


def _build(match_data=None):
    from db.parse_match_data import build_match_rows

    with patch(
        "db.parse_match_data.get_embeddings", side_effect=_fake_embeddings
    ) as mock_embed:
        rows = build_match_rows(
            match_data if match_data is not None else make_match_data_ranked_game(),
            latest_version="14.1.1",
            google_genai_client=MagicMock(),
        )
    return rows, mock_embed


def _write(fake_bq, bodies: dict[str, str]):
    from db.parse_match_data import write_matches

    with patch("db.parse_match_data.get_embeddings", side_effect=_fake_embeddings):
        return write_matches(fake_bq, bodies, "14.1.1", MagicMock())


class TestBuildMatchRows:
    def test_skips_non_ranked_match(self):
        rows, mock_embed = _build(make_match_data_unranked_game())

        assert rows is None
        mock_embed.assert_not_called()

    def test_builds_rows_for_every_table(self):
        match_data = make_match_data_ranked_game()
        rows, _ = _build()

        assert set(rows) == {
            "matches",
            "players",
            "participants",
            "participant_traits",
            "participant_units",
            "unit_items",
        }
        (match_row,) = rows["matches"]
        assert match_row["match_id"] == match_data["metadata"]["match_id"]
        assert match_row["queue_id"] == 1100
        assert match_row["game_version"] == "14.1.1"
        assert len(rows["participants"]) == len(match_data["info"]["participants"])
        assert rows["participant_units"] and rows["unit_items"]

    def test_played_at_is_utc_timestamp_on_every_per_match_row(self):
        rows, _ = _build()

        # game_datetime 1760517800896 ms in the fixture
        assert rows["matches"][0]["played_at"] == "2025-10-15T08:43:20.896000+00:00"
        for table in ("participants", "participant_traits", "participant_units", "unit_items"):
            assert {r["played_at"] for r in rows[table]} == {
                rows["matches"][0]["played_at"]
            }

    def test_embeds_all_participants_in_one_call(self):
        match_data = make_match_data_ranked_game()
        rows, mock_embed = _build()

        assert mock_embed.call_count == 1
        compositions = mock_embed.call_args.args[1]
        assert len(compositions) == len(match_data["info"]["participants"])
        assert all(len(row["embedding"]) == 768 for row in rows["participants"])

    def test_players_row_for_every_participant(self):
        match_data = make_match_data_ranked_game()
        rows, _ = _build()

        platform = match_data["metadata"]["match_id"].split("_")[0]
        assert {r["puuid"] for r in rows["players"]} == {
            p["puuid"] for p in match_data["info"]["participants"]
        }
        assert all(r["region"] == platform for r in rows["players"])
        assert all(r["game_name"] for r in rows["players"])

    def test_keeps_duplicate_copies_of_the_same_champion(self):
        import copy

        # deepcopy: the helper returns a shared module-level constant
        match_data = copy.deepcopy(make_match_data_ranked_game())
        participant = match_data["info"]["participants"][0]
        participant["units"] = [
            {"character_id": "TFT16_Jinx", "tier": 2, "itemNames": ["A"], "rarity": 1},
            {"character_id": "TFT16_Jinx", "tier": 1, "itemNames": ["B", "C"], "rarity": 1},
        ]
        rows, _ = _build(match_data)

        puuid = participant["puuid"]
        units = [r for r in rows["participant_units"] if r["puuid"] == puuid]
        assert [(u["slot"], u["champion"], u["star"]) for u in units] == [
            (0, "TFT16_Jinx", 2),
            (1, "TFT16_Jinx", 1),
        ]
        items = [r for r in rows["unit_items"] if r["puuid"] == puuid]
        assert [(i["slot"], i["item_index"], i["item"]) for i in items] == [
            (0, 0, "A"),
            (1, 0, "B"),
            (1, 1, "C"),
        ]


class TestWriteMatches:
    def test_stages_schema_shaped_rows_and_drops_staging_tables(self, fake_bq):
        match_data = make_match_data_ranked_game()
        # FakeBigQuery fails the test if a row doesn't fit its Terraform schema
        assert _write(fake_bq, {"m": json.dumps(match_data)}) == (1, 0)

        assert len(fake_bq.staged("participants")) == len(
            match_data["info"]["participants"]
        )
        assert sorted(fake_bq.deleted) == sorted(fake_bq.loads)
        assert all(".tft_staging." in ref for ref in fake_bq.loads)

    def test_one_script_for_the_whole_batch(self, fake_bq):
        import copy

        second = copy.deepcopy(make_match_data_ranked_game())
        second["metadata"]["match_id"] = "SG2_2"
        bodies = {
            "a": json.dumps(make_match_data_ranked_game()),
            "b": json.dumps(second),
        }

        assert _write(fake_bq, bodies) == (2, 0)
        assert len(fake_bq.queries) == 1
        assert {r["match_id"] for r in fake_bq.staged("matches")} == {
            "SG2_106316155",
            "SG2_2",
        }

    def test_matches_row_goes_out_first_and_in_last(self, fake_bq):
        _write(fake_bq, {"m": json.dumps(make_match_data_ranked_game())})

        (sql, _), = fake_bq.queries
        statements = [s.strip() for s in sql.split(";") if s.strip()]
        assert statements[0].startswith("DELETE FROM `test-project.tft.matches`")
        assert statements[-1].startswith("INSERT INTO `test-project.tft.matches`")
        for table in ("participants", "participant_traits", "participant_units", "unit_items"):
            assert f"DELETE FROM `test-project.tft.{table}`" in sql
            assert f"INSERT INTO `test-project.tft.{table}`" in sql
        assert "MERGE `test-project.tft.players`" in sql

    def test_deletes_are_bounded_by_match_ids_and_dates(self, fake_bq):
        _write(fake_bq, {"m": json.dumps(make_match_data_ranked_game())})

        (_, params), = fake_bq.queries
        by_name = {p.name: p for p in params}
        assert by_name["match_ids"].values == ["SG2_106316155"]
        assert by_name["lo"].value == by_name["hi"].value

    def test_skips_unranked_and_counts_unparseable(self, fake_bq):
        bodies = {
            "ranked": json.dumps(make_match_data_ranked_game()),
            "unranked": json.dumps(make_match_data_unranked_game()),
            "broken": "{",
        }

        assert _write(fake_bq, bodies) == (1, 1)
        assert len(fake_bq.staged("matches")) == 1

    def test_nothing_to_write_runs_no_jobs(self, fake_bq):
        assert _write(fake_bq, {"u": json.dumps(make_match_data_unranked_game())}) == (0, 0)
        assert not fake_bq.queries and not fake_bq.loads


# ---------------------------------------------------------------------------
# filter_new_match_ids
# ---------------------------------------------------------------------------


class TestFilterNewMatchIds:
    def test_drops_ids_already_in_matches(self):
        from db.parse_match_data import filter_new_match_ids
        from tests.conftest import FakeBigQuery

        fake_bq = FakeBigQuery(query_rows=[{"match_id": "NA1_2"}])

        result = filter_new_match_ids(fake_bq, ["NA1_1", "NA1_2", "NA1_3"])

        assert result == ["NA1_1", "NA1_3"]
        (sql, params), = fake_bq.queries
        assert "`test-project.tft.matches`" in sql
        assert params[0].values == ["NA1_1", "NA1_2", "NA1_3"]

    def test_empty_input_runs_no_query(self, fake_bq):
        from db.parse_match_data import filter_new_match_ids

        assert filter_new_match_ids(fake_bq, []) == []
        assert not fake_bq.queries


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

    async def test_one_riot_call_per_tier_and_one_write(self, fake_bq):
        from db.upsert_players import upsert_high_elo_players

        with patch(
            "db.upsert_players.get_league_entries", return_value=self.LEAGUE
        ) as mock_league:
            written = await upsert_high_elo_players(
                MagicMock(), "OC1", fake_bq, tiers=["CHALLENGER", "GRANDMASTER"]
            )

        assert mock_league.call_count == 2
        assert written == 4
        assert len(fake_bq.staged("players")) == 4
        assert len(fake_bq.staged("player_ranked_stats")) == 4
        (sql, _), = fake_bq.queries
        assert "MERGE `test-project.tft.players`" in sql
        assert "MERGE `test-project.tft.player_ranked_stats`" in sql

    async def test_empty_league_writes_nothing(self, fake_bq):
        from db.upsert_players import upsert_high_elo_players

        with patch(
            "db.upsert_players.get_league_entries", return_value={"entries": []}
        ):
            assert await upsert_high_elo_players(MagicMock(), "OC1", fake_bq) == 0
        assert not fake_bq.queries and not fake_bq.loads

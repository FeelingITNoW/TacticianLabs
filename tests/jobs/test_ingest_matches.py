"""Tests for the Cloud Run Job entrypoint (include/jobs/ingest_matches.py)."""

import copy
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from db.parse_match_data import (
    build_match_rows,
    filter_new_match_ids,
    select_matches,
    write_rejected_matches,
)
from google_embedding.embedding_call import make_genai_client
from jobs import ingest_matches
from jobs.ingest_matches import groups_for_task, groups_from_env, routing_groups
from riot_api.constants import (
    HIGH_ELO_TIERS,
    INGEST_QUEUES,
    MASTER_CRAWL_BATCH,
    ROUTING_MATCH_TARGET,
    RANKED_QUEUES,
    RIOT_REGIONS,
    RIOT_REGIONS_MAP,
    VALID_RANK_TIERS,
    allowed_queues,
)
from riot_api.league_api import _APEX_TIER_PATHS, get_masters
from riot_api.match_api import collect_match_ids
from tests.dags.test_constants import MATCH_DATA_RANKED_GAME


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


class TestHighEloTiers:
    def test_masters_are_ingested_with_the_other_apex_tiers(self):
        assert HIGH_ELO_TIERS == ["CHALLENGER", "GRANDMASTER", "MASTER"]

    def test_every_tier_is_valid_and_has_a_league_endpoint(self):
        assert set(HIGH_ELO_TIERS) <= set(VALID_RANK_TIERS)
        assert set(HIGH_ELO_TIERS) <= set(_APEX_TIER_PATHS)

    async def test_match_ids_are_collected_for_master_players_too(self):
        histories = {"c1": ["NA1_1"], "g1": ["NA1_2"], "m1": ["NA1_2", "NA1_3"]}

        async def history(client, puuid, startTime, region):
            return histories[puuid]

        with (
            patch("riot_api.match_api.get_challengers", AsyncMock(return_value=["c1"])),
            patch("riot_api.match_api.get_grandmasters", AsyncMock(return_value=["g1"])),
            patch("riot_api.match_api.get_masters", AsyncMock(return_value=["m1"])) as masters,
            patch("riot_api.match_api.get_match_history_from_last_n_days", history),
        ):
            match_ids, _ = await collect_match_ids(MagicMock(), ["NA1"], HIGH_ELO_TIERS)

        masters.assert_awaited_once()
        assert sorted(match_ids) == ["NA1_1", "NA1_2", "NA1_3"]

    async def test_master_players_and_ranked_stats_are_upserted(self, fake_bq):
        from db.upsert_players import upsert_high_elo_players

        league = AsyncMock(return_value={"entries": []})
        with patch("db.upsert_players.get_league_entries", league):
            await upsert_high_elo_players(MagicMock(), "NA1", fake_bq)

        assert [call.args[2] for call in league.await_args_list] == HIGH_ELO_TIERS


RANKED, NORMAL, HYPER_ROLL = 1100, 1090, 1130


def body(match_id: str, queue_id: int) -> str:
    """A fetched match: just enough of the payload for select_matches."""
    return json.dumps(
        {"info": {"queue_id": queue_id, "game_datetime": 1_790_000_000_000}, "id": match_id}
    )


class TestAllowedQueues:
    def test_ranked_from_every_tier(self):
        for tier in HIGH_ELO_TIERS:
            assert RANKED in allowed_queues([tier])

    def test_normals_only_from_challengers(self):
        assert NORMAL in allowed_queues(["CHALLENGER"])
        assert NORMAL not in allowed_queues(["GRANDMASTER"])
        assert NORMAL not in allowed_queues(["MASTER"])
        assert NORMAL not in allowed_queues(["GRANDMASTER", "MASTER"])

    def test_a_match_is_judged_by_the_union_of_its_tiers(self):
        assert NORMAL in allowed_queues(["CHALLENGER", "MASTER"])

    def test_other_modes_never_and_no_information_means_ranked_only(self):
        assert HYPER_ROLL not in INGEST_QUEUES
        assert allowed_queues([]) == RANKED_QUEUES
        assert allowed_queues(["BRONZE"]) == RANKED_QUEUES


class TestMasterCap:
    ENTRIES = [{"puuid": f"m{i}", "leaguePoints": i} for i in range(600)]

    async def test_get_masters_keeps_the_highest_lp(self):
        league = AsyncMock(return_value={"entries": list(self.ENTRIES)})
        with patch("riot_api.league_api.get_league_entries", league):
            top = await get_masters(MagicMock(), "NA1", limit=3)
            everyone = await get_masters(MagicMock(), "NA1")

        assert top == ["m599", "m598", "m597"]
        assert len(everyone) == 600

    async def test_a_match_remembers_every_tier_that_had_it(self):
        histories = {"c1": ["NA1_1", "NA1_2"], "g1": ["NA1_2"], "m1": ["NA1_2", "NA1_3"]}

        async def history(client, puuid, startTime, region):
            return histories[puuid]

        with (
            patch("riot_api.match_api.get_challengers", AsyncMock(return_value=["c1"])),
            patch("riot_api.match_api.get_grandmasters", AsyncMock(return_value=["g1"])),
            patch("riot_api.match_api.get_masters", AsyncMock(return_value=["m1"])),
            patch("riot_api.match_api.get_match_history_from_last_n_days", history),
        ):
            sources, routing = await collect_match_ids(MagicMock(), ["NA1"], HIGH_ELO_TIERS)

        assert routing == "AMERICAS"
        assert sources == {
            "NA1_1": ["CHALLENGER"],
            "NA1_2": ["CHALLENGER", "GRANDMASTER", "MASTER"],
            "NA1_3": ["MASTER"],
        }


class TestCrawlPriority:
    """C and GM in full, then Masters round-robin until the routing region has its target."""

    def crawl(self, players, histories, filter_new=list):
        """Run collect_match_ids over fake leagues; returns (result, puuids crawled in order)."""
        crawled: list[str] = []

        async def history(client, puuid, startTime, region):
            crawled.append(puuid)
            return histories.get(puuid, [])

        async def run(regions, target):
            with (
                patch(
                    "riot_api.match_api.get_challengers",
                    AsyncMock(side_effect=lambda c, r: players["CHALLENGER"][r]),
                ),
                patch(
                    "riot_api.match_api.get_grandmasters",
                    AsyncMock(side_effect=lambda c, r: players["GRANDMASTER"][r]),
                ),
                patch(
                    "riot_api.match_api.get_masters",
                    AsyncMock(side_effect=lambda c, r: players["MASTER"][r]),
                ),
                patch("riot_api.match_api.get_match_history_from_last_n_days", history),
            ):
                return await collect_match_ids(
                    MagicMock(), regions, HIGH_ELO_TIERS, target, filter_new
                )

        return run, crawled

    def test_the_target_is_2000_new_matches_per_routing_region(self):
        assert ROUTING_MATCH_TARGET == 2000

    async def test_challengers_then_grandmasters_then_masters(self):
        players = {
            "CHALLENGER": {"NA1": ["c1"]},
            "GRANDMASTER": {"NA1": ["g1"]},
            "MASTER": {"NA1": ["m1"]},
        }
        run, crawled = self.crawl(
            players, {"c1": ["NA1_1"], "g1": ["NA1_2"], "m1": ["NA1_2", "NA1_3"]}
        )

        sources, _ = await run(["NA1"], 10)

        assert crawled == ["c1", "g1", "m1"]
        assert list(sources) == ["NA1_1", "NA1_2", "NA1_3"]

    async def test_challengers_and_grandmasters_are_crawled_in_full_even_past_the_target(self):
        players = {
            "CHALLENGER": {"NA1": ["c1", "c2"]},
            "GRANDMASTER": {"NA1": ["g1", "g2"]},
            "MASTER": {"NA1": ["m1"]},
        }
        histories = {p: [f"NA1_{p}_{i}" for i in range(3)] for p in ("c1", "c2", "g1", "g2", "m1")}
        run, crawled = self.crawl(players, histories)

        sources, _ = await run(["NA1"], 5)

        assert crawled == ["c1", "c2", "g1", "g2"]  # no Master: 12 matches > target
        assert len(sources) == 12

    async def test_masters_fill_the_room_left_and_stop_at_the_target(self):
        masters = [f"m{i}" for i in range(100)]
        players = {
            "CHALLENGER": {"NA1": ["c1"]},
            "GRANDMASTER": {"NA1": []},
            "MASTER": {"NA1": masters},
        }
        histories = {"c1": ["NA1_c0", "NA1_c1"]}
        histories.update({m: [f"NA1_{m}_{i}" for i in range(5)] for m in masters})
        run, crawled = self.crawl(players, histories)

        sources, _ = await run(["NA1"], 30)

        assert len(sources) == 30  # trimmed to exactly the target
        assert list(sources)[:2] == ["NA1_c0", "NA1_c1"]  # priority order kept
        # Stops at batch granularity instead of crawling all 100 Masters
        assert len(crawled) - 1 <= 6 + MASTER_CRAWL_BATCH

    async def test_masters_are_interleaved_by_lp_rank_across_platforms(self):
        players = {
            "CHALLENGER": {"NA1": [], "BR1": []},
            "GRANDMASTER": {"NA1": [], "BR1": []},
            "MASTER": {"NA1": ["na1", "na2", "na3"], "BR1": ["br1"]},
        }
        run, crawled = self.crawl(players, {})

        await run(["NA1", "BR1"], None)

        assert crawled == ["na1", "br1", "na2", "na3"]

    async def test_matches_that_are_not_new_do_not_count_toward_the_target(self):
        players = {
            "CHALLENGER": {"NA1": ["c1"]},
            "GRANDMASTER": {"NA1": []},
            "MASTER": {"NA1": [f"m{i}" for i in range(60)]},
        }
        histories = {"c1": ["NA1_old_1", "NA1_new_1"]}
        histories.update({f"m{i}": [f"NA1_old_m{i}", f"NA1_new_m{i}"] for i in range(60)})
        run, crawled = self.crawl(
            players, histories, filter_new=lambda ids: [i for i in ids if "_new_" in i]
        )

        sources, _ = await run(["NA1"], 25)

        assert len(sources) == 25
        assert all("_new_" in match_id for match_id in sources)
        assert len(crawled) > 25  # the stored matches were crawled but not counted

    async def test_a_match_carries_every_tier_that_had_it_in_priority_order(self):
        players = {
            "CHALLENGER": {"NA1": ["c1"]},
            "GRANDMASTER": {"NA1": ["g1"]},
            "MASTER": {"NA1": ["m1"]},
        }
        run, _ = self.crawl(
            players, {"c1": ["NA1_a"], "g1": ["NA1_a", "NA1_b"], "m1": ["NA1_b", "NA1_c"]}
        )

        sources, _ = await run(["NA1"], 10)

        assert sources == {
            "NA1_a": ["CHALLENGER", "GRANDMASTER"],
            "NA1_b": ["GRANDMASTER", "MASTER"],
            "NA1_c": ["MASTER"],
        }

    async def test_the_target_applies_per_routing_region(self):
        players = {
            "CHALLENGER": {"NA1": ["c_na"], "EUW1": ["c_eu"]},
            "GRANDMASTER": {"NA1": [], "EUW1": []},
            "MASTER": {
                "NA1": [f"na{i}" for i in range(50)],
                "EUW1": [f"eu{i}" for i in range(50)],
            },
        }
        histories = {p: [f"{p}_{i}" for i in range(4)] for r in players.values() for ps in r.values() for p in ps}
        run, _ = self.crawl(players, histories)

        sources, routing = await run(["NA1", "EUW1"], 20)

        assert routing == "EUROPE"
        assert sum(m.startswith(("c_na", "na")) for m in sources) == 20
        assert sum(m.startswith(("c_eu", "eu")) for m in sources) == 20


class TestSelectMatches:
    def select(self, queue_id, tiers):
        accepted, rejected = select_matches(
            {"NA1_1": body("NA1_1", queue_id)}, {"NA1_1": tiers}
        )
        return accepted, rejected

    @pytest.mark.parametrize("tiers", [["CHALLENGER"], ["GRANDMASTER"], ["MASTER"]])
    def test_ranked_is_recorded_from_any_tier(self, tiers):
        accepted, rejected = self.select(RANKED, tiers)

        assert list(accepted) == ["NA1_1"] and rejected == []

    def test_a_normal_game_is_recorded_when_a_challenger_played_it(self):
        accepted, rejected = self.select(NORMAL, ["CHALLENGER"])
        assert list(accepted) == ["NA1_1"] and rejected == []

        accepted, rejected = self.select(NORMAL, ["CHALLENGER", "MASTER"])
        assert list(accepted) == ["NA1_1"] and rejected == []

    @pytest.mark.parametrize("tiers", [["GRANDMASTER"], ["MASTER"], ["GRANDMASTER", "MASTER"]])
    def test_a_normal_game_nobody_challenger_played_is_rejected(self, tiers):
        accepted, (row,) = self.select(NORMAL, tiers)

        assert accepted == {}
        assert row["match_id"] == "NA1_1"
        assert row["queue_id"] == NORMAL
        assert row["reason"] == "normal_not_challenger"

    @pytest.mark.parametrize("tiers", [["CHALLENGER"], ["MASTER"]])
    def test_other_modes_are_rejected_even_for_challengers(self, tiers):
        accepted, (row,) = self.select(HYPER_ROLL, tiers)

        assert accepted == {}
        assert (row["queue_id"], row["reason"]) == (HYPER_ROLL, "queue")

    def test_rejected_rows_match_the_table_and_carry_the_game_time(self, fake_bq):
        _, rejected = self.select(NORMAL, ["MASTER"])

        write_rejected_matches(fake_bq, rejected)

        (staged_row,) = fake_bq.staged("rejected_matches")
        assert staged_row["played_at"].startswith("2026-")
        assert staged_row["match_id"] == "NA1_1"

    def test_an_unreadable_body_is_kept_so_it_counts_as_a_failure(self):
        accepted, rejected = select_matches({"NA1_1": "not json"}, {"NA1_1": ["MASTER"]})

        assert list(accepted) == ["NA1_1"] and rejected == []

    def test_a_match_with_no_source_is_judged_as_ranked_only(self):
        accepted, rejected = select_matches(
            {"NA1_1": body("NA1_1", NORMAL), "NA1_2": body("NA1_2", RANKED)}, {}
        )

        assert list(accepted) == ["NA1_2"]
        assert [row["match_id"] for row in rejected] == ["NA1_1"]


class TestBuildMatchRowsQueues:
    def match(self, queue_id):
        data = copy.deepcopy(MATCH_DATA_RANKED_GAME)
        data["info"]["queue_id"] = queue_id
        return data

    def test_normal_games_are_skipped_unless_asked_for(self):
        assert build_match_rows(self.match(NORMAL), "16.19.1", None) is None

    def test_normal_games_are_built_with_the_ingest_queues(self):
        rows = build_match_rows(self.match(NORMAL), "16.19.1", None, INGEST_QUEUES)

        assert rows["matches"][0]["queue_id"] == NORMAL

    def test_other_modes_are_skipped_even_with_the_ingest_queues(self):
        assert build_match_rows(self.match(HYPER_ROLL), "16.19.1", None, INGEST_QUEUES) is None


class TestRejectedMatchCache:
    def test_rejected_matches_are_merged_in_without_duplicates(self, fake_bq):
        _, rejected = select_matches(
            {"NA1_1": body("NA1_1", HYPER_ROLL)}, {"NA1_1": ["MASTER"]}
        )

        write_rejected_matches(fake_bq, rejected)

        (sql, _), = fake_bq.queries
        assert "MERGE `test-project.tft.rejected_matches`" in sql
        assert "WHEN NOT MATCHED THEN INSERT" in sql
        assert "WHEN MATCHED" not in sql
        assert len(fake_bq.staged("rejected_matches")) == 1

    def test_nothing_to_remember_runs_no_query(self, fake_bq):
        write_rejected_matches(fake_bq, [])

        assert not fake_bq.queries and not fake_bq.loads

    def test_ids_are_checked_against_the_rejected_table_too(self):
        from tests.conftest import FakeBigQuery

        fake_bq = FakeBigQuery(query_rows=[{"match_id": "NA1_2"}])

        assert filter_new_match_ids(fake_bq, ["NA1_1", "NA1_2"]) == ["NA1_1"]

        (sql, _), = fake_bq.queries
        assert "`test-project.tft.matches`" in sql
        assert "`test-project.tft.rejected_matches`" in sql


class TestIngestRoutingGroup:
    SOURCES = {
        "NA1_ranked": ["MASTER"],
        "NA1_normal_challenger": ["CHALLENGER"],
        "NA1_normal_master": ["MASTER"],
        "NA1_hyper": ["CHALLENGER"],
        "NA1_cached": ["MASTER"],
    }
    BODIES = {
        "NA1_ranked": body("NA1_ranked", RANKED),
        "NA1_normal_challenger": body("NA1_normal_challenger", NORMAL),
        "NA1_normal_master": body("NA1_normal_master", NORMAL),
        "NA1_hyper": body("NA1_hyper", HYPER_ROLL),
    }

    async def run(self, write_rejected=None):
        mocks = {
            "upsert_high_elo_players": AsyncMock(),
            # The crawl already dropped NA1_cached, which was rejected on an earlier run
            "collect_match_ids": AsyncMock(
                return_value=(
                    {k: v for k, v in self.SOURCES.items() if k != "NA1_cached"},
                    "AMERICAS",
                )
            ),
            "filter_new_match_ids": MagicMock(
                side_effect=lambda client, ids: [i for i in ids if i != "NA1_cached"]
            ),
            "collect_matches": AsyncMock(return_value=dict(self.BODIES)),
            "upload_matches": AsyncMock(),
            "write_matches": MagicMock(side_effect=lambda c, bodies, *a: (len(bodies), 0)),
            "write_rejected_matches": write_rejected or MagicMock(),
        }
        with patch.multiple(ingest_matches, **mocks):
            failures = await ingest_matches.ingest_routing_group(
                MagicMock(), MagicMock(), None, MagicMock(), "AMERICAS", ["NA1"], "16.19.1", None
            )
        return failures, mocks

    async def test_the_crawl_only_counts_matches_not_stored_or_rejected(self):
        _, mocks = await self.run()

        filter_new = mocks["collect_match_ids"].await_args.kwargs["filter_new"]
        assert filter_new(["NA1_ranked", "NA1_cached"]) == ["NA1_ranked"]

    async def test_cached_matches_are_never_fetched(self):
        _, mocks = await self.run()

        fetched = mocks["collect_matches"].await_args.args[1]
        assert "NA1_cached" not in fetched
        assert sorted(fetched) == sorted(set(self.SOURCES) - {"NA1_cached"})

    async def test_only_matches_worth_recording_are_archived_and_written(self):
        failures, mocks = await self.run()

        archived = mocks["upload_matches"].await_args.args[0]
        written = mocks["write_matches"].call_args.args[1]
        assert sorted(archived) == sorted(written) == ["NA1_normal_challenger", "NA1_ranked"]
        assert mocks["write_matches"].call_args.args[-1] == INGEST_QUEUES
        assert failures == 0

    async def test_the_rest_are_remembered(self):
        _, mocks = await self.run()

        (rejected,) = mocks["write_rejected_matches"].call_args.args[1:]
        assert {row["match_id"]: row["reason"] for row in rejected} == {
            "NA1_normal_master": "normal_not_challenger",
            "NA1_hyper": "queue",
        }

    async def test_a_failed_cache_write_does_not_fail_the_run(self):
        failing = MagicMock(side_effect=RuntimeError("BigQuery down"))

        failures, mocks = await self.run(write_rejected=failing)

        assert failures == 0
        mocks["write_matches"].assert_called_once()

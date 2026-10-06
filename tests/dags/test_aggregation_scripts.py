import re

import pytest

from data_aggregation.data_aggregation import (
    TOTALS,
    check_sql,
    check_totals,
    counts_sql,
    live_resolver,
    merge_sql,
    merge_totals_sql,
    new_resolver,
    old_resolver,
    rebuild_sql,
    rebuild_totals,
    value_columns,
)
from db.bq import column_names

STAGING = {
    "matches": "test-project.tft_staging.matches_abc",
    "participants": "test-project.tft_staging.participants_abc",
    "participant_units": "test-project.tft_staging.participant_units_abc",
    "participant_traits": "test-project.tft_staging.participant_traits_abc",
    "unit_items": "test-project.tft_staging.unit_items_abc",
}


def statements(sql: str) -> list[str]:
    return [s.strip() for s in sql.split(";") if s.strip()]


class TestCounts:
    @pytest.mark.parametrize(
        "totals,source,column",
        [
            ("champion_totals", "participant_units", "champion"),
            ("trait_totals", "participant_traits", "trait"),
            ("item_totals", "unit_items", "item"),
        ],
    )
    def test_reads_the_right_source(self, fake_bq, totals, source, column):
        sql = counts_sql(totals, live_resolver(fake_bq))

        assert f"FROM `test-project.tft.{source}`" in sql
        assert f"{column} AS api_name" in sql

    def test_only_active_traits_count(self, fake_bq):
        live = live_resolver(fake_bq)

        assert "tier_current > 0" in counts_sql("trait_totals", live)
        assert "tier_current" not in counts_sql("champion_totals", live)
        assert "tier_current" not in counts_sql("item_totals", live)

    def test_counts_each_board_once(self, fake_bq):
        # Two copies of a champion must not count as two boards
        for totals, spec in TOTALS.items():
            if spec.source is not None:
                assert "SELECT DISTINCT match_id, puuid" in counts_sql(
                    totals, live_resolver(fake_bq)
                )

    def test_champion_item_combo_joins_items_to_their_unit(self, fake_bq):
        sql = counts_sql("champion_item_totals", live_resolver(fake_bq))

        assert "USING (match_id, puuid, slot)" in sql
        assert "u.champion, i.item" in sql

    def test_patch_is_the_match_game_version(self, fake_bq):
        for totals in TOTALS:
            assert "m.game_version AS patch" in counts_sql(totals, live_resolver(fake_bq))

    def test_sign_flips_every_counter(self, fake_bq):
        sql = counts_sql("champion_totals", live_resolver(fake_bq), sign=-1)

        for counter in ("boards", "matches", "placement_sum", "top4_count", "win_count"):
            assert re.search(rf"-1 \* [^\n]* AS {counter}\b", sql)

    @pytest.mark.parametrize("totals", list(TOTALS))
    def test_columns_line_up_with_the_table(self, fake_bq, totals):
        assert [*value_columns(totals), "updated_at"] == column_names(fake_bq, totals)


class TestResolvers:
    def test_new_reads_staging(self, fake_bq):
        t = new_resolver(fake_bq, STAGING)

        assert t("participants") == "`test-project.tft_staging.participants_abc`"

    def test_unstaged_table_is_empty(self, fake_bq):
        t = new_resolver(fake_bq, {})

        assert t("unit_items") == "(SELECT * FROM `test-project.tft.unit_items` WHERE FALSE)"

    def test_old_is_bounded_by_the_write_parameters(self, fake_bq):
        sql = old_resolver(fake_bq)("participants")

        assert "FROM `test-project.tft.participants`" in sql
        assert "match_id IN UNNEST(@match_ids)" in sql
        assert "played_at BETWEEN @lo AND @hi" in sql


class TestMerge:
    def test_adds_new_counts_and_subtracts_the_rows_being_replaced(self, fake_bq):
        sql = merge_sql(
            fake_bq,
            "champion_totals",
            new_resolver(fake_bq, STAGING),
            old_resolver(fake_bq),
        )

        assert "MERGE `test-project.tft.champion_totals` AS t" in sql
        assert "`test-project.tft_staging.participant_units_abc`" in sql
        assert "UNION ALL" in sql
        assert "-1 * COUNT(*) AS boards" in sql
        assert "boards = t.boards + s.boards" in sql
        assert "WHEN MATCHED AND t.boards + s.boards <= 0 THEN DELETE" in sql
        assert "WHEN NOT MATCHED AND s.boards > 0 THEN INSERT" in sql

    def test_patch_totals_keeps_the_newest_match_time(self, fake_bq):
        sql = merge_sql(
            fake_bq, "patch_totals", new_resolver(fake_bq, STAGING), old_resolver(fake_bq)
        )

        assert "last_played_at = GREATEST(t.last_played_at, s.last_played_at)" in sql
        assert "ON t.patch = s.patch" in sql

    def test_keys_the_combo_table_on_patch_champion_and_item(self, fake_bq):
        sql = merge_sql(
            fake_bq,
            "champion_item_totals",
            new_resolver(fake_bq, STAGING),
            old_resolver(fake_bq),
        )

        assert "t.patch = s.patch AND t.champion = s.champion AND t.item = s.item" in sql

    def test_insert_columns_match_the_table(self, fake_bq):
        for name in TOTALS:
            sql = merge_sql(
                fake_bq, name, new_resolver(fake_bq, STAGING), old_resolver(fake_bq)
            )
            insert_columns = sql.split("INSERT (")[1].split(")")[0]
            assert [c.strip() for c in insert_columns.split(",")] == column_names(
                fake_bq, name
            )

    def test_one_statement_per_totals_table(self, fake_bq):
        merges = merge_totals_sql(fake_bq, STAGING)

        assert len(merges) == len(TOTALS)
        for name, sql in zip(TOTALS, merges):
            assert f"MERGE `test-project.tft.{name}`" in sql


class TestRebuild:
    def test_replaces_every_table_in_one_transaction(self, fake_bq):
        stmts = statements(rebuild_sql(fake_bq))

        assert stmts[0] == "BEGIN TRANSACTION"
        assert stmts[-1] == "COMMIT TRANSACTION"
        for name in TOTALS:
            assert f"DELETE FROM `test-project.tft.{name}` WHERE TRUE" in stmts
            assert any(s.startswith(f"INSERT INTO `test-project.tft.{name}`") for s in stmts)

    def test_insert_columns_match_the_table(self, fake_bq):
        sql = rebuild_sql(fake_bq)

        for name in TOTALS:
            insert = sql.split(f"INSERT INTO `test-project.tft.{name}` (")[1]
            insert_columns = insert.split(")")[0]
            assert [c.strip() for c in insert_columns.split(",")] == column_names(
                fake_bq, name
            )

    def test_runs_one_query(self, fake_bq):
        rebuild_totals(fake_bq)

        assert len(fake_bq.queries) == 1


class TestCheck:
    def test_reports_mismatches_per_table(self, fake_bq):
        fake_bq.query_rows = [{"mismatches": 2}]

        assert check_totals(fake_bq) == {name: 2 for name in TOTALS}
        assert len(fake_bq.queries) == len(TOTALS)

    def test_diffs_both_directions_without_writing(self, fake_bq):
        sql = check_sql(fake_bq, "item_totals")

        assert sql.count("EXCEPT DISTINCT") == 2
        assert "DELETE" not in sql and "INSERT" not in sql


@pytest.mark.integration
class TestTotalsSqlCompiles:
    """Dry-runs the counting, merge and check queries against the real dataset.

    Free and reads nothing. Needs Application Default Credentials and the
    Terraform in infra/gcp applied.
    """

    @pytest.fixture
    def client(self):
        import google.auth
        from google.auth.exceptions import DefaultCredentialsError

        from db.bq import make_client

        try:
            google.auth.default()
        except DefaultCredentialsError:
            pytest.skip("no Google Application Default Credentials")
        return make_client()

    @staticmethod
    def dry_run(client, sql, params=()):
        from google.cloud import bigquery

        return client.query(
            sql,
            job_config=bigquery.QueryJobConfig(
                dry_run=True, use_query_cache=False, query_parameters=list(params)
            ),
        )

    @pytest.mark.parametrize("totals", list(TOTALS))
    def test_counts(self, client, totals):
        job = self.dry_run(client, counts_sql(totals, live_resolver(client)))

        assert [f.name for f in job.schema] == value_columns(totals)

    @pytest.mark.parametrize("totals", list(TOTALS))
    def test_merge(self, client, totals):
        from datetime import datetime, timezone

        from google.cloud import bigquery

        params = [
            bigquery.ArrayQueryParameter("match_ids", "STRING", ["x"]),
            bigquery.ScalarQueryParameter("lo", "TIMESTAMP", datetime.now(timezone.utc)),
            bigquery.ScalarQueryParameter("hi", "TIMESTAMP", datetime.now(timezone.utc)),
        ]
        # The live tables stand in for the staged ones, which share their layout
        sql = merge_sql(client, totals, live_resolver(client), old_resolver(client))
        self.dry_run(client, sql, params)

    @pytest.mark.parametrize("totals", list(TOTALS))
    def test_check(self, client, totals):
        self.dry_run(client, check_sql(client, totals))

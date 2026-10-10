"""Tests for the stored champion/item names (include/db/reference_names.py), the
participants' board summary (include/db/board_summary.py) and the backfill_names
command (include/jobs/backfill_names.py)."""

import pytest

from db.board_summary import backfill_board_summary_sql, insert_participants_sql
from db.reference_names import (
    NAME_COLUMNS,
    backfill_names_sql,
    insert_with_names_sql,
)
from jobs import backfill_names

STAGING = {
    "participants": "test-project.tft_staging.participants_x",
    "participant_units": "test-project.tft_staging.participant_units_x",
    "unit_items": "test-project.tft_staging.unit_items_x",
}


@pytest.fixture(autouse=True)
def use_fake_bq(fake_bq, monkeypatch):
    monkeypatch.setattr(backfill_names, "make_client", lambda: fake_bq)


class TestInsertWithNamesSql:
    def test_looks_up_the_champion_name(self, fake_bq):
        sql = insert_with_names_sql(
            fake_bq, "participant_units", "test-project.tft_staging.participant_units_x"
        )

        assert sql.startswith(
            "INSERT INTO `test-project.tft.participant_units` "
            "(match_id, puuid, played_at, slot, champion, star, rarity, champion_name)"
        )
        assert "s.rarity, r.name AS champion_name FROM" in sql
        assert "s.champion_name" not in sql
        assert (
            "LEFT JOIN `test-project.tft.champions` AS r ON r.api_name = s.champion;"
            in sql
        )

    def test_looks_up_the_item_name(self, fake_bq):
        sql = insert_with_names_sql(
            fake_bq, "unit_items", "test-project.tft_staging.unit_items_x"
        )

        assert "r.name AS item_name" in sql
        assert "LEFT JOIN `test-project.tft.items` AS r ON r.api_name = s.item;" in sql


class TestBackfillNamesSql:
    @pytest.mark.parametrize("table", list(NAME_COLUMNS))
    def test_updates_only_missing_or_stale_names(self, fake_bq, table):
        name_column, key, reference = NAME_COLUMNS[table]

        sql = backfill_names_sql(fake_bq, table)

        assert sql.startswith(
            f"UPDATE `test-project.tft.{table}` AS t SET {name_column} = r.name"
        )
        assert f"FROM `test-project.tft.{reference}` AS r" in sql
        assert f"t.{key} = r.api_name AND t.{name_column} IS DISTINCT FROM r.name" in sql


class TestInsertParticipantsSql:
    def test_keeps_the_staged_columns_and_adds_the_board_summary(self, fake_bq):
        sql = insert_participants_sql(fake_bq, STAGING)

        assert sql.startswith(
            "INSERT INTO `test-project.tft.participants` (match_id, puuid, played_at, "
            "placement, level, gold_left, last_round, total_damage_to_players, embedding, "
            "completed_items, board_cost)"
        )
        assert "s.embedding, COALESCE(ci.completed_items, 0) AS completed_items, " in sql
        assert "COALESCE(bc.board_cost, 0) AS board_cost\n" in sql
        assert "s.completed_items" not in sql and "s.board_cost" not in sql
        assert sql.rstrip().endswith(";")

    def test_completed_items_are_the_items_that_are_not_components(self, fake_bq):
        sql = insert_participants_sql(fake_bq, STAGING)

        assert "COUNTIF(r.item_type IS DISTINCT FROM 'component') AS completed_items" in sql
        assert "FROM `test-project.tft_staging.unit_items_x` AS i" in sql
        assert "LEFT JOIN `test-project.tft.items` AS r ON r.api_name = i.item" in sql

    def test_board_cost_weighs_each_unit_by_the_copies_its_star_level_takes(self, fake_bq):
        sql = insert_participants_sql(fake_bq, STAGING)

        assert (
            "SUM(COALESCE(c.cost, 0) * CAST(POW(3, COALESCE(u.star, 1) - 1) AS INT64)) AS board_cost"
            in sql
        )
        assert "FROM `test-project.tft_staging.participant_units_x` AS u" in sql
        assert "LEFT JOIN `test-project.tft.champions` AS c ON c.api_name = u.champion" in sql

    def test_aggregates_units_and_items_apart_so_neither_multiplies_the_other(self, fake_bq):
        sql = insert_participants_sql(fake_bq, STAGING)

        assert sql.count("GROUP BY") == 2
        assert ") AS ci ON ci.match_id = s.match_id AND ci.puuid = s.puuid" in sql
        assert ") AS bc ON bc.match_id = s.match_id AND bc.puuid = s.puuid" in sql

    def test_no_staged_items_or_units_means_zero(self, fake_bq):
        sql = insert_participants_sql(fake_bq, {"participants": STAGING["participants"]})

        assert "0 AS completed_items, 0 AS board_cost" in sql
        assert "JOIN" not in sql


class TestBackfillBoardSummarySql:
    def test_recounts_from_the_stored_tables_and_rewrites_only_changed_rows(self, fake_bq):
        sql = backfill_board_summary_sql(fake_bq)

        assert sql.startswith(
            "UPDATE `test-project.tft.participants` AS t "
            "SET completed_items = b.completed_items, board_cost = b.board_cost"
        )
        assert "FROM `test-project.tft.participants` AS s" in sql
        assert "FROM `test-project.tft.participant_units` AS u" in sql
        assert "FROM `test-project.tft.unit_items` AS i" in sql
        assert (
            "WHERE t.match_id = b.match_id AND t.puuid = b.puuid AND "
            "(t.completed_items IS DISTINCT FROM b.completed_items "
            "OR t.board_cost IS DISTINCT FROM b.board_cost);"
        ) in sql


class TestMain:
    def test_backfills_every_table_in_one_script(self, fake_bq, capsys):
        assert backfill_names.main([]) == 0

        (sql, _), = fake_bq.queries
        assert "UPDATE `test-project.tft.participant_units`" in sql
        assert "UPDATE `test-project.tft.unit_items`" in sql
        assert "UPDATE `test-project.tft.participants`" in sql
        assert (
            "Backfilled participant_units, unit_items, participants" in capsys.readouterr().out
        )

    def test_participants_alone(self, fake_bq):
        backfill_names.main(["--table", "participants"])

        (sql, _), = fake_bq.queries
        assert sql.startswith("UPDATE `test-project.tft.participants`")
        assert "champion_name" not in sql

    def test_table_limits_it(self, fake_bq):
        backfill_names.main(["--table", "unit_items"])

        (sql, _), = fake_bq.queries
        assert "unit_items" in sql
        assert "participant_units" not in sql

    def test_an_unknown_table_is_rejected(self):
        with pytest.raises(SystemExit):
            backfill_names.main(["--table", "matches"])


@pytest.mark.integration
class TestNameSqlCompiles:
    """Dry-runs the insert and backfill against the real dataset. Free and reads
    nothing. Needs Application Default Credentials and the Terraform in infra/gcp applied."""

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
    def dry_run(client, sql):
        from google.cloud import bigquery

        return client.query(
            sql, job_config=bigquery.QueryJobConfig(dry_run=True, use_query_cache=False)
        )

    @pytest.mark.parametrize("table", list(NAME_COLUMNS))
    def test_insert_compiles(self, client, table):
        from db.bq import table_ref

        # The live table stands in for a staging table, which has the same layout
        self.dry_run(client, insert_with_names_sql(client, table, table_ref(client, table)))

    @pytest.mark.parametrize("table", list(NAME_COLUMNS))
    def test_backfill_compiles(self, client, table):
        self.dry_run(client, backfill_names_sql(client, table))

    def test_participants_insert_compiles(self, client):
        from db.bq import table_ref

        live = {name: table_ref(client, name) for name in STAGING}
        self.dry_run(client, insert_participants_sql(client, live))

    def test_board_summary_backfill_compiles(self, client):
        self.dry_run(client, backfill_board_summary_sql(client))

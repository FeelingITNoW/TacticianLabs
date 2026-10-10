"""Tests for the stored champion/item names (include/db/reference_names.py) and the
backfill_names command (include/jobs/backfill_names.py)."""

import pytest

from db.reference_names import (
    NAME_COLUMNS,
    backfill_names_sql,
    insert_with_names_sql,
)
from jobs import backfill_names


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


class TestMain:
    def test_backfills_every_table_in_one_script(self, fake_bq, capsys):
        assert backfill_names.main([]) == 0

        (sql, _), = fake_bq.queries
        assert "UPDATE `test-project.tft.participant_units`" in sql
        assert "UPDATE `test-project.tft.unit_items`" in sql
        assert (
            "Backfilled names in participant_units, unit_items" in capsys.readouterr().out
        )

    def test_table_limits_it(self, fake_bq):
        backfill_names.main(["--table", "unit_items"])

        (sql, _), = fake_bq.queries
        assert "unit_items" in sql
        assert "participant_units" not in sql

    def test_an_unknown_table_is_rejected(self):
        with pytest.raises(SystemExit):
            backfill_names.main(["--table", "participants"])


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

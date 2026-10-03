import pytest

from data_aggregation.data_aggregation import (
    STATS_SOURCES,
    refresh_stats,
    stats_select_sql,
    stats_sql,
)


class TestStatsSql:
    @pytest.mark.parametrize(
        "stats_table,source,column",
        [
            ("champion_stats", "participant_units", "champion"),
            ("trait_stats", "participant_traits", "trait"),
            ("item_stats", "unit_items", "item"),
        ],
    )
    def test_reads_the_right_source(self, fake_bq, stats_table, source, column):
        sql = stats_select_sql(fake_bq, stats_table)

        assert f"FROM `test-project.tft.{source}`" in sql
        assert f"{column} AS api_name" in sql

    def test_only_active_traits_count(self, fake_bq):
        assert "tier_current > 0" in stats_select_sql(fake_bq, "trait_stats")
        assert "tier_current" not in stats_select_sql(fake_bq, "champion_stats")
        assert "tier_current" not in stats_select_sql(fake_bq, "item_stats")

    def test_counts_each_board_once(self, fake_bq):
        # Two copies of a champion must not count as two games
        for stats_table in STATS_SOURCES:
            assert "SELECT DISTINCT match_id, puuid" in stats_select_sql(
                fake_bq, stats_table
            )

    def test_swaps_contents_in_one_transaction(self, fake_bq):
        statements = [
            s.strip() for s in stats_sql(fake_bq, "item_stats").split(";") if s.strip()
        ]

        assert statements[0] == "BEGIN TRANSACTION"
        assert statements[1] == "DELETE FROM `test-project.tft.item_stats` WHERE TRUE"
        assert statements[2].startswith("INSERT INTO `test-project.tft.item_stats`")
        assert statements[-1] == "COMMIT TRANSACTION"

    def test_insert_columns_match_the_table(self, fake_bq):
        from db.bq import column_names

        sql = stats_sql(fake_bq, "champion_stats")
        insert_columns = sql.split("INSERT INTO")[1].split("(")[1].split(")")[0]
        assert [c.strip() for c in insert_columns.split(",")] == column_names(
            fake_bq, "champion_stats"
        )

    def test_refresh_runs_one_query(self, fake_bq):
        refresh_stats(fake_bq, "trait_stats")

        assert len(fake_bq.queries) == 1


@pytest.mark.integration
class TestStatsSqlCompiles:
    """Dry-runs each stats query against the real dataset (free, reads nothing).

    Needs Application Default Credentials and the Terraform in infra/gcp applied.
    """

    @pytest.mark.parametrize("stats_table", list(STATS_SOURCES))
    def test_dry_run(self, stats_table):
        from google.cloud import bigquery

        import google.auth
        from google.auth.exceptions import DefaultCredentialsError

        from db.bq import column_names, make_client

        try:
            google.auth.default()
        except DefaultCredentialsError:
            pytest.skip("no Google Application Default Credentials")

        client = make_client()
        job = client.query(
            stats_select_sql(client, stats_table),
            job_config=bigquery.QueryJobConfig(dry_run=True, use_query_cache=False),
        )
        assert [f.name for f in job.schema] == column_names(client, stats_table)

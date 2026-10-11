"""Tests for the 3-item build tool (include/insights/item_trios.py)."""

from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from google.api_core import exceptions

from insights import item_trios as module
from insights.item_trios import item_trios

PROJECT = "test-project"
ROUTINE = (
    Path(__file__).parents[2]
    / "infra"
    / "gcp"
    / "bigquery"
    / "routines"
    / "champion_item_trios.sql.tftpl"
)
WINDOW = (
    datetime(2026, 9, 24, tzinfo=timezone.utc),
    datetime(2026, 10, 8, tzinfo=timezone.utc),
)


class FakeClient:
    """Answers the champion, patch, window and trios queries in turn."""

    project = PROJECT

    def __init__(self, champion=None, rows=None, error=None):
        self.champion = champion
        self.rows = rows or []
        self.error = error
        self.sent: list[tuple[str, list]] = []

    def query(self, sql, job_config=None):
        params = (
            {p.name: p.value for p in job_config.query_parameters} if job_config else {}
        )
        self.sent.append((sql, params))
        if "FROM `test-project.tft.champions`" in sql:
            found = [{"api_name": self.champion}] if self.champion else []
            return SimpleNamespace(result=lambda: found)
        if "FROM `test-project.tft.patch_totals`" in sql:
            return SimpleNamespace(result=lambda: [{"patch": "16.19.1"}])
        if "MIN(played_at)" in sql:
            return SimpleNamespace(result=lambda: [{"lo": WINDOW[0], "hi": WINDOW[1]}])
        if self.error:
            raise self.error
        return SimpleNamespace(result=lambda: self.rows)


def test_unknown_champion_never_runs_the_trios_query():
    client = FakeClient(champion=None)
    log: list[str] = []

    rows = item_trios(client, "Nobody", 30, log)

    assert "Nobody" in rows[0]["error"]
    assert log == []


def test_passes_the_resolved_champion_patch_and_window():
    client = FakeClient(
        champion="DA_18_KhaZix", rows=[{"games": 40, "day": date(2026, 10, 1)}]
    )
    log: list[str] = []

    rows = item_trios(client, "Kha'Zix", 30, log)

    sql, params = client.sent[-1]
    assert params == {
        "champion": "DA_18_KhaZix",
        "patch": "16.19.1",
        "lo": WINDOW[0],
        "hi": WINDOW[1],
        "min_games": 30,
    }
    assert log == [sql]
    assert rows == [{"games": 40, "day": "2026-10-01"}]


def test_the_query_calls_the_shared_function_with_only_parameters():
    sql = module.trios_sql(FakeClient())

    assert "FROM `test-project.tft.champion_item_trios`(@champion, @patch, @lo, @hi, @min_games)" in sql
    assert "ORDER BY average_placement" in sql
    assert f"LIMIT {module.MAX_TRIOS}" in sql
    # The model's output keeps display names under the old column names
    assert "item_a_name AS item_a" in sql


def test_the_function_is_fixed_and_prunes_every_table_by_day():
    """The SQL lives in the BigQuery function; check it still reads one patch's days only."""
    sql = ROUTINE.read_text()

    assert "HAVING COUNT(*) = 3" in sql
    assert "m.queue_id = ${ranked_queue_id}" in sql
    assert "m.game_version = p_patch" in sql
    for alias in ("u", "i", "p", "m"):
        assert f"{alias}.played_at BETWEEN p_lo AND p_hi" in sql
    # Arguments are p_-prefixed: a bare `patch` or `champion` would resolve to the columns
    for bare in ("= patch", "= champion", "@"):
        assert bare not in sql.replace("ch.patch = p_patch", "")


def test_returns_a_bigquery_error_to_the_model():
    client = FakeClient(champion="DA_18_KhaZix", error=exceptions.BadRequest("boom"))

    rows = item_trios(client, "Kha'Zix", 30, [])

    assert "boom" in rows[0]["error"]


@pytest.mark.integration
def test_trios_sql_compiles():
    """Dry-runs the trios query against the real dataset. Free; needs Application Default Credentials."""
    import google.auth
    from google.auth.exceptions import DefaultCredentialsError
    from google.cloud import bigquery

    from db.bq import make_client

    try:
        google.auth.default()
    except DefaultCredentialsError:
        pytest.skip("no Google Application Default Credentials")
    client = make_client()
    params = [
        bigquery.ScalarQueryParameter("champion", "STRING", "x"),
        bigquery.ScalarQueryParameter("patch", "STRING", "x"),
        bigquery.ScalarQueryParameter("lo", "TIMESTAMP", WINDOW[0]),
        bigquery.ScalarQueryParameter("hi", "TIMESTAMP", WINDOW[1]),
        bigquery.ScalarQueryParameter("min_games", "INT64", 30),
    ]

    job = client.query(
        module.trios_sql(client),
        job_config=bigquery.QueryJobConfig(
            dry_run=True, use_query_cache=False, query_parameters=params
        ),
    )

    assert [f.name for f in job.schema] == [
        "item_a",
        "item_b",
        "item_c",
        "games",
        "win_rate",
        "top4_rate",
        "average_placement",
        "share_of_champion_games",
    ]
    print(f"{job.total_bytes_processed} bytes for the dry run")

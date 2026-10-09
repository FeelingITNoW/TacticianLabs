"""Tests for the natural-language-to-SQL agent (include/insights/nl_to_sql.py)."""

from datetime import date
from types import SimpleNamespace

from google.api_core import exceptions

from insights import nl_to_sql, prompt

PROJECT = "test-project"


class FakeClient:
    """Stands in for bigquery.Client: dry runs report `tables`, real runs return `rows`."""

    project = PROJECT

    def __init__(self, tables=None, rows=None, statement_type="SELECT", error=None):
        self.tables = tables if tables is not None else ["current_champion_stats"]
        self.rows = rows or []
        self.statement_type = statement_type
        self.error = error
        self.ran: list[str] = []

    def query(self, sql, job_config=None):
        if job_config is not None and job_config.dry_run:
            if self.error:
                raise self.error
            return SimpleNamespace(
                statement_type=self.statement_type,
                referenced_tables=[
                    SimpleNamespace(
                        project=PROJECT, dataset_id=nl_to_sql.DATASET, table_id=t
                    )
                    for t in self.tables
                ],
            )
        self.ran.append(sql)
        return SimpleNamespace(result=lambda max_results=None: self.rows[:max_results])


def test_runs_a_select_over_an_allowed_view():
    client = FakeClient(rows=[{"name": "KhaZix", "played": date(2026, 9, 28)}])
    log: list[str] = []

    rows = nl_to_sql.run_sql(client, "SELECT 1", log)

    assert rows == [{"name": "KhaZix", "played": "2026-09-28"}]
    assert log == ["SELECT 1"]


def test_refuses_a_table_outside_the_views():
    client = FakeClient(tables=["participants"])

    rows = nl_to_sql.run_sql(client, "SELECT * FROM participants", [])

    assert "error" in rows[0]
    assert client.ran == []


def test_refuses_anything_but_a_select():
    client = FakeClient(statement_type="DELETE")

    rows = nl_to_sql.run_sql(client, "DELETE FROM x WHERE TRUE", [])

    assert "error" in rows[0]
    assert client.ran == []


def test_caps_the_rows():
    client = FakeClient(rows=[{"n": i} for i in range(nl_to_sql.MAX_ROWS + 50)])

    assert len(nl_to_sql.run_sql(client, "SELECT 1", [])) == nl_to_sql.MAX_ROWS


def test_returns_a_bigquery_error_to_the_model():
    client = FakeClient(error=exceptions.BadRequest("Unrecognized name: foo"))

    rows = nl_to_sql.run_sql(client, "SELECT foo", [])

    assert "Unrecognized name: foo" in rows[0]["error"]


def test_context_names_every_view_and_section(monkeypatch):
    monkeypatch.setattr(nl_to_sql, "_contexts", {})
    columns = [
        SimpleNamespace(table_name=view, column_name="games", data_type="INT64")
        for view in prompt.VIEWS
    ]
    client = SimpleNamespace(
        project=PROJECT,
        query=lambda sql, job_config=None: SimpleNamespace(result=lambda: columns),
    )

    context = nl_to_sql.build_context(client)

    for view in prompt.VIEWS:
        assert f"{view}(games INT64)" in context
    assert prompt.GLOSSARY.strip() in context
    assert f"{PROJECT}.{nl_to_sql.DATASET}.current_champion_stats" in context

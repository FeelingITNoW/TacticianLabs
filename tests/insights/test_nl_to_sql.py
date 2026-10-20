"""Tests for the natural-language-to-SQL agent (include/insights/nl_to_sql.py)."""

from datetime import date
from types import SimpleNamespace

import pytest
from google.genai import types
from google.api_core import exceptions

from insights import nl_to_sql, prompt

PROJECT = "test-project"


@pytest.fixture(autouse=True)
def clear_allowed_cache():
    nl_to_sql._allowed.clear()


class FakeClient:
    """Stands in for bigquery.Client: dry runs report `tables`, real runs return `rows`."""

    project = PROJECT

    def __init__(
        self, tables=None, rows=None, statement_type="SELECT", error=None, base=("champions",)
    ):
        self.tables = tables if tables is not None else ["current_champion_stats"]
        # What a dry run over any one view reports: the tables that view reads
        self.base = list(base)
        self.rows = rows or []
        self.statement_type = statement_type
        self.error = error
        self.ran: list[str] = []

    def query(self, sql, job_config=None):
        if job_config is not None and job_config.dry_run:
            if self.error:
                raise self.error
            tables = self.base if sql.startswith("SELECT * FROM `") else self.tables
            return SimpleNamespace(
                statement_type=self.statement_type,
                referenced_tables=[
                    SimpleNamespace(
                        project=PROJECT, dataset_id=nl_to_sql.DATASET, table_id=t
                    )
                    for t in tables
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


def test_allows_a_query_whose_dry_run_lists_the_views_base_tables():
    # BigQuery expands views, so a dry run over a view reports what it reads, not the view
    client = FakeClient(
        tables=["champion_item_totals", "champions", "items"],
        base=("champion_item_totals", "champions", "items"),
        rows=[{"n": 1}],
    )

    rows = nl_to_sql.run_sql(client, "SELECT 1", [])

    assert rows == [{"n": 1}]
    assert client.ran == ["SELECT 1"]


def test_history_goes_before_the_question_and_is_trimmed():
    history = [
        {"role": "user" if i % 2 == 0 else "model", "text": f"t{i}"} for i in range(10)
    ]

    contents = nl_to_sql.build_contents("and on Sivir?", history)

    assert [c.parts[0].text for c in contents] == [
        "t4", "t5", "t6", "t7", "t8", "t9", "and on Sivir?"
    ]
    assert contents[-1].role == "user"
    assert [c.role for c in contents[:2]] == ["user", "model"]


def test_no_history_is_just_the_question():
    contents = nl_to_sql.build_contents("hi", None)

    assert len(contents) == 1 and contents[0].parts[0].text == "hi"


def usage(prompt, output, total):
    return SimpleNamespace(
        prompt_token_count=prompt,
        candidates_token_count=output,
        thoughts_token_count=None,
        cached_content_token_count=None,
        total_token_count=total,
    )


class FakeGenai:
    """A genai client whose models.generate_content returns `responses` in turn."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.requests = []
        self.models = SimpleNamespace(generate_content=self.generate_content)

    def generate_content(self, model, contents, config):
        self.requests.append(len(contents))
        return self.responses.pop(0)


def tool_call(query="SELECT 1"):
    call = SimpleNamespace(name="sql", args={"query": query})
    content = types.Content(role="model", parts=[types.Part(text="calling")])
    return SimpleNamespace(
        function_calls=[call],
        text=None,
        candidates=[SimpleNamespace(content=content)],
        usage_metadata=usage(100, 5, 105),
    )


def final(text="done", prompt=150, output=20):
    return SimpleNamespace(
        function_calls=None,
        text=text,
        candidates=[],
        usage_metadata=usage(prompt, output, prompt + output),
    )


@pytest.fixture
def agent_env(monkeypatch):
    monkeypatch.setenv("GEMINI_SQL_MODEL", "gemini-test")
    monkeypatch.setattr(nl_to_sql, "build_context", lambda client: "system prompt")


def test_ask_adds_up_every_model_call(agent_env):
    client = FakeClient(rows=[{"n": 1}])
    genai_client = FakeGenai([tool_call(), final()])

    answer = nl_to_sql.ask("how many?", client=client, genai_client=genai_client)

    assert answer.text == "done"
    assert answer.queries == ["SELECT 1"]
    assert [c.total_tokens for c in answer.model_calls] == [105, 170]
    assert [c.prompt_tokens for c in answer.model_calls] == [100, 150]
    assert [r.rows for r in answer.sql_runs] == [1]
    assert answer.model == "gemini-test"
    assert len(answer.prompt_sha256) == 64
    # The second request carries the question, the model's call and the tool result
    assert genai_client.requests == [1, 3]


def test_ask_stops_when_the_model_never_finishes(agent_env):
    genai_client = FakeGenai([tool_call() for _ in range(nl_to_sql.MAX_TOOL_CALLS)])

    answer = nl_to_sql.ask("q", client=FakeClient(), genai_client=genai_client)

    assert answer.text.startswith("No answer")
    assert len(answer.model_calls) == nl_to_sql.MAX_TOOL_CALLS


def test_a_failed_ask_keeps_what_it_used(agent_env):
    genai_client = FakeGenai([tool_call()])  # the second call finds nothing to pop

    with pytest.raises(IndexError) as raised:
        nl_to_sql.ask("q", client=FakeClient(), genai_client=genai_client)

    assert [c.total_tokens for c in raised.value.answer.model_calls] == [105]


def test_run_sql_records_refused_and_run_queries():
    runs: list[nl_to_sql.SqlRun] = []

    nl_to_sql.run_sql(FakeClient(statement_type="DML"), "DELETE x", [], runs)
    nl_to_sql.run_sql(FakeClient(rows=[{"n": 1}, {"n": 2}]), "SELECT 1", [], runs)

    assert runs[0].error and runs[0].rows == 0
    assert runs[1].error is None and runs[1].rows == 2


def test_instructions_tell_the_agent_to_link_the_comps_it_discusses():
    assert "[<label>](/compositions/<comp_id>)" in prompt.INSTRUCTIONS
    assert "?variant=<variant_id>" in prompt.INSTRUCTIONS

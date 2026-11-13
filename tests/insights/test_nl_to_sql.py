"""Tests for the natural-language-to-SQL agent (include/insights/nl_to_sql.py)."""

from datetime import date
from types import SimpleNamespace

import pytest
from google.genai import types
from google.api_core import exceptions

from ai_tools.gold_projection import Augment
from insights import nl_to_sql, prompt

PROJECT = "test-project"


@pytest.fixture(autouse=True)
def clear_allowed_cache():
    nl_to_sql._allowed.clear()
    nl_to_sql._unit_costs.clear()


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


UNITS = [
    {"name": "Lillia", "cost": 4},
    {"name": "Ahri", "cost": 4},
    {"name": "Kha'Zix", "cost": 3},
]


def roll_odds_call(**args):
    call = SimpleNamespace(name="roll_odds", args=args)
    content = types.Content(role="model", parts=[types.Part(text="calling")])
    return SimpleNamespace(
        function_calls=[call],
        text=None,
        candidates=[SimpleNamespace(content=content)],
        usage_metadata=usage(100, 5, 105),
    )


def test_roll_odds_finds_units_by_name_and_records_the_run():
    answer = nl_to_sql.Answer(text="")
    units = [{"name": "lillia", "copies": 3}, {"name": "KHAZIX", "copies": 1}]

    result = nl_to_sql.run_roll_odds(FakeClient(rows=UNITS), 8, units, None, [60], answer)

    assert [u["name"] for u in result["units"]] == ["Lillia", "Kha'Zix"]
    assert [u["cost"] for u in result["units"]] == [4, 3]
    assert result["results"][0]["gold"] == 60
    assert 0 < result["results"][0]["all_units"] < 1
    assert answer.roll_odds_runs[0].error is None
    assert answer.roll_odds_runs[0].args["units"] == units


def test_roll_odds_gives_the_curve_to_the_page_and_not_to_the_model():
    answer = nl_to_sql.Answer(text="")

    result = nl_to_sql.run_roll_odds(
        FakeClient(rows=UNITS), 8, [{"name": "Lillia", "copies": 3}], None, [60], answer
    )

    assert "curve" not in result
    [shown] = answer.roll_odds
    assert shown["results"] == result["results"]
    # 3 four-cost copies are 12 gold, then a point per 2-gold roll, covering at least 100 gold
    assert shown["curve"][0]["gold"] == 12 and shown["curve"][1]["gold"] == 14
    assert shown["curve"][-1]["gold"] >= 100


def test_roll_odds_reads_the_units_once():
    client = FakeClient(rows=UNITS)
    answer = nl_to_sql.Answer(text="")

    for _ in range(2):
        nl_to_sql.run_roll_odds(client, 8, [{"name": "Ahri", "copies": 1}], None, [60], answer)

    assert len(client.ran) == 1


def test_roll_odds_tier_out_and_copies_out_lower_the_odds():
    client = FakeClient(rows=UNITS)
    answer = nl_to_sql.Answer(text="")
    units = [{"name": "Ahri", "copies": 2}]
    held = [{"name": "Ahri", "copies": 2, "copies_out": 4}]

    open_pool = nl_to_sql.run_roll_odds(client, 8, units, None, [80], answer)
    thin = nl_to_sql.run_roll_odds(client, 8, held, [{"cost": 4, "copies": 30}], [80], answer)

    assert thin["tier_out"] == [{"cost": 4, "copies": 30}]
    assert thin["results"][0]["all_units"] < open_pool["results"][0]["all_units"]


def test_roll_odds_unknown_unit_lists_the_valid_names():
    answer = nl_to_sql.Answer(text="")

    result = nl_to_sql.run_roll_odds(
        FakeClient(rows=UNITS), 8, [{"name": "Lilia", "copies": 3}], None, None, answer
    )

    assert "Unknown unit(s): Lilia" in result["error"]
    assert "Ahri, Kha'Zix, Lillia" in result["error"]
    assert answer.roll_odds == []
    assert answer.roll_odds_runs[0].error == result["error"]


@pytest.mark.parametrize(
    "level, units",
    [
        (1, [{"name": "Ahri", "copies": 1}]),
        (8, [{"name": "Ahri", "copies": 0}]),
        (8, [{"name": "Ahri"}]),
        (8, []),
    ],
)
def test_roll_odds_refused_input_goes_back_to_the_model(level, units):
    answer = nl_to_sql.Answer(text="")

    result = nl_to_sql.run_roll_odds(FakeClient(rows=UNITS), level, units, None, None, answer)

    assert "error" in result
    assert answer.roll_odds == [] and answer.roll_odds_runs[0].error


def test_ask_dispatches_each_call_to_its_tool(agent_env):
    genai_client = FakeGenai(
        [
            roll_odds_call(level=8, units=[{"name": "Ahri", "copies": 2}], gold=[60]),
            tool_call("SELECT 1"),
            final(),
        ]
    )

    answer = nl_to_sql.ask("odds?", client=FakeClient(rows=UNITS), genai_client=genai_client)

    assert answer.text == "done"
    assert answer.queries == ["SELECT 1"]
    assert len(answer.roll_odds) == 1 and len(answer.roll_odds_runs) == 1


def test_ask_answers_an_unknown_tool_and_bad_arguments_with_an_error(agent_env):
    wrong_name = roll_odds_call()
    wrong_name.function_calls[0].name = "drop_tables"
    genai_client = FakeGenai([wrong_name, roll_odds_call(lvl=8), final()])

    answer = nl_to_sql.ask("q", client=FakeClient(rows=UNITS), genai_client=genai_client)

    assert answer.text == "done"
    assert answer.roll_odds_runs == [] and answer.queries == []


def test_instructions_make_the_agent_ask_for_the_level_and_leave_the_chart_to_the_page():
    assert "ask for it" in prompt.INSTRUCTIONS
    assert "do not describe or draw a chart yourself" in prompt.INSTRUCTIONS
    assert "roll_odds" in prompt.EXAMPLES


MASTERLIST = {
    "Pot of Gold": Augment("Pot of Gold", gold=8),
    "Cruel Pact": Augment("Cruel Pact", free_rolls=1, max_interest=2),
}


@pytest.fixture
def masterlist(monkeypatch):
    monkeypatch.setattr(nl_to_sql, "augment_masterlist", lambda: MASTERLIST)


def projection(answer, end_round="4-2", augments=None, **start):
    args = {
        "start_round": None,
        "start_level": None,
        "start_xp": None,
        "start_gold": None,
        "start_streak": None,
        **start,
    }
    args.setdefault("scenarios", None)
    return nl_to_sql.run_gold_projection(end_round, augments, answer=answer, **args)


def gold_projection_call(**args):
    call = SimpleNamespace(name="gold_projection", args=args)
    content = types.Content(role="model", parts=[types.Part(text="calling")])
    return SimpleNamespace(
        function_calls=[call],
        text=None,
        candidates=[SimpleNamespace(content=content)],
        usage_metadata=usage(100, 5, 105),
    )


def test_gold_projection_defaults_to_4_2_and_records_the_run(masterlist):
    answer = nl_to_sql.Answer(text="")

    result = projection(answer)

    assert result["end_round"] == "4-2" and result["start"]["round"] == "2-1"
    assert [s["preset"] for s in result["scenarios"]] == ["win", "mixed", "loss"]
    assert all(s["ceiling"] for s in result["scenarios"])
    assert answer.gold_projection_runs[0].error is None
    assert answer.gold_projection_runs[0].args["end_round"] == "4-2"


def test_gold_projection_gives_the_series_to_the_page_and_not_to_the_model(masterlist):
    answer = nl_to_sql.Answer(text="")

    result = projection(answer, "3-2")

    assert all("series" not in s for s in result["scenarios"])
    [shown] = answer.gold_projections
    assert shown["scenarios"][0]["series"][-1]["round"] == "3-2"
    assert shown["scenarios"][0]["gold"] == result["scenarios"][0]["gold"]


def test_gold_projection_finds_augments_by_name_and_slot(masterlist):
    answer = nl_to_sql.Answer(text="")
    pick = [{"name": "pot of gold", "slot": "2-1"}]

    with_augment = projection(answer, "3-2", pick)
    without = projection(answer, "3-2")

    assert with_augment["augments"][0]["name"] == "Pot of Gold"
    assert with_augment["augments"][0]["slot"] == "2-1"
    assert with_augment["scenarios"][0]["gold"] > without["scenarios"][0]["gold"]


def test_gold_projection_start_overrides_replace_the_defaults(masterlist):
    answer = nl_to_sql.Answer(text="")

    result = projection(
        answer, "3-3", start_round="3-2", start_level=6, start_xp=1, start_gold=40, start_streak=2
    )

    assert result["start"] == {"round": "3-2", "level": 6, "xp": 1, "gold": 40, "streak": 2}


def test_gold_projection_unknown_augment_lists_the_valid_names(masterlist):
    answer = nl_to_sql.Answer(text="")

    result = projection(answer, augments=[{"name": "Nope", "slot": "2-1"}])

    assert "Nope" in result["error"] and "Cruel Pact, Pot of Gold" in result["error"]
    assert answer.gold_projections == []
    assert answer.gold_projection_runs[0].error == result["error"]


def test_gold_projection_with_an_empty_masterlist_says_so(monkeypatch):
    monkeypatch.setattr(nl_to_sql, "augment_masterlist", lambda: {})
    answer = nl_to_sql.Answer(text="")

    result = projection(answer, augments=[{"name": "Nope", "slot": "2-1"}])

    assert "masterlist is empty" in result["error"]


@pytest.mark.parametrize(
    "args",
    [
        dict(end_round="6-1"),
        dict(end_round="soon"),
        dict(augments=[{"name": "Pot of Gold", "slot": "3-3"}]),
        dict(augments=[{"name": "Pot of Gold"}]),
        dict(start_level=40),
    ],
)
def test_gold_projection_refused_input_goes_back_to_the_model(masterlist, args):
    answer = nl_to_sql.Answer(text="")

    result = projection(answer, **args)

    assert "error" in result
    assert answer.gold_projections == [] and answer.gold_projection_runs[0].error


def test_ask_dispatches_gold_projection_calls(agent_env, masterlist):
    genai_client = FakeGenai(
        [
            gold_projection_call(
                end_round="3-2", augments=[{"name": "Pot of Gold", "slot": "2-1"}]
            ),
            final(),
        ]
    )

    answer = nl_to_sql.ask("gold?", client=FakeClient(rows=UNITS), genai_client=genai_client)

    assert answer.text == "done"
    assert len(answer.gold_projections) == 1 and len(answer.gold_projection_runs) == 1
    assert answer.gold_projection_runs[0].error is None


def test_ask_answers_bad_gold_projection_arguments_with_an_error(agent_env):
    genai_client = FakeGenai([gold_projection_call(end_rnd="3-2"), final()])

    answer = nl_to_sql.ask("q", client=FakeClient(rows=UNITS), genai_client=genai_client)

    assert answer.gold_projection_runs == []


def test_instructions_state_the_gold_projection_caveats_and_chain_it_with_roll_odds():
    text = prompt.INSTRUCTIONS
    assert "gold_projection" in text and "gold_projection" in prompt.EXAMPLES
    assert "ceiling" in text and "extremes" in text and "board units" in text
    assert "both level 8 and level 9" in text
    assert "do not describe or draw them yourself" in text
    assert "level_above" not in text and "one letter per PvP fight" in text


def custom_scenarios():
    return [
        {
            "fights": "w" * 11,
            "label": "Level on curve",
            "gold": [{"round": "2-2", "gold": 0}],
            "levels": [{"round": "2-1", "level": 4}],
        },
        {"fights": "l" * 11, "levels": [{"round": "4-2", "level": 5}]},
    ]


def test_gold_projection_runs_custom_scenarios_and_lets_the_fights_set_the_end_round(masterlist):
    answer = nl_to_sql.Answer(text="")

    result = projection(answer, None, scenarios=custom_scenarios())

    assert result["end_round"] == "4-2"
    assert [s["label"] for s in result["scenarios"]] == ["Level on curve", "Custom 2"]
    assert all("series" not in s for s in result["scenarios"])
    assert answer.gold_projection_runs[0].args["scenarios"] == custom_scenarios()


def test_gold_projection_turns_the_moves_into_rounds_and_amounts(masterlist):
    answer = nl_to_sql.Answer(text="")
    scenarios = [
        {
            "fights": "win",
            "gold": [{"round": "2-1", "gold": -3}, {"round": "2-2", "gold": 12}],
            "levels": [{"round": "2-5", "level": 5}],
        }
    ]

    projection(answer, "2-6", scenarios=scenarios)

    [shown] = answer.gold_projections
    points = {p["round"]: p for p in shown["scenarios"][0]["series"]}
    assert points["2-1"]["spent"] == 3 and points["2-2"]["gained"] == 12
    assert points["2-5"]["leveling"] > 0


def test_gold_projection_takes_a_carousel_value_per_round(masterlist):
    answer = nl_to_sql.Answer(text="")
    scenarios = [{"fights": "w" * 4, "carousels": [{"round": "2-4", "gold": 1}]}]

    projection(answer, "2-6", scenarios=scenarios)

    [shown] = answer.gold_projections
    points = {p["round"]: p for p in shown["scenarios"][0]["series"]}
    assert points["2-4"]["income"]["carousel"] == 1


@pytest.mark.parametrize(
    "scenarios, message",
    [
        ([{"fights": "www"}, {"fights": "wwww"}], "different rounds"),
        ([{"fights": "w" * 11, "gold": [{"round": "2-2", "gold": -500}]}], "needs 500 gold"),
        ([{"fights": "w" * 11, "gold": [{"round": "2-2", "gold": -1}] * 2}], "more than once"),
        ([{"fights": "w" * 11, "gold": [{"round": "soon", "gold": -1}]}], "round must look like"),
        ([{"label": "no fights"}], "fights"),
        ([{"fights": "win"}] * 4, "at most 3"),
        ([{"fights": "win", "level_above": 50}], "level_above"),
        ([{"fights": "w" * 4, "carousels": [{"round": "2-4", "gold": 9}]}], "worth 1 to 3"),
        ([{"fights": "w" * 4, "carousels": [{"round": "2-4", "gold": 2}] * 2}], "more than once"),
        ([{"fights": "w" * 4, "gold": [{"round": "2-4", "gold": -1}]}], "carousel"),
    ],
)
def test_gold_projection_bad_scenarios_go_back_to_the_model(masterlist, scenarios, message):
    answer = nl_to_sql.Answer(text="")

    result = projection(answer, None, scenarios=scenarios)

    assert message in result["error"]
    assert answer.gold_projections == [] and answer.gold_projection_runs[0].error


def test_ask_dispatches_custom_gold_projection_scenarios(agent_env, masterlist):
    genai_client = FakeGenai([gold_projection_call(scenarios=custom_scenarios()), final()])

    answer = nl_to_sql.ask("plan?", client=FakeClient(rows=UNITS), genai_client=genai_client)

    assert len(answer.gold_projections) == 1
    assert answer.gold_projection_runs[0].error is None

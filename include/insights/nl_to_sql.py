"""Answer questions about TFT stats by letting Gemini write SQL against the stats views.

Run with `PYTHONPATH=include python -m insights.nl_to_sql "which champions are best"`.
Needs Application Default Credentials, GOOGLE_CLOUD_PROJECT, GEMINI_API_KEY and
GEMINI_SQL_MODEL (the Gemini model that writes the SQL).

The model gets two tools. `sql` (run_sql) dry-runs each query first and refuses
anything that isn't a SELECT over prompt.VIEWS or that would bill more than
MAX_BYTES_BILLED. Every view reads precomputed counters (3-item builds and comps' star
levels, items and board costs included), so a question costs kilobytes to megabytes.
`roll_odds` (run_roll_odds) looks the units' costs up in current_champion_stats and gives the
odds of rolling a board at several amounts of gold (ai_tools/roll_odds.py).
Errors go back to the model as the tool result, so it can fix its own call. The text the model reads lives in insights/prompt.py.
"""

import argparse
import hashlib
import inspect
import os
import re
import sys
import time
from dataclasses import dataclass, field

from google import genai
from google.api_core import exceptions
from google.cloud import bigquery
from google.genai import types
from pydantic import BaseModel

from ai_tools import roll_odds as roll_odds_calculator
from db.bq import DATASET, make_client, table_ref
from insights import prompt
from insights.common import MAX_BYTES_BILLED, MAX_ROWS, json_rows

MAX_TOOL_CALLS = 8
MAX_HISTORY_TURNS = 6

_contexts: dict[str, str] = {}
_allowed: dict[str, set[str]] = {}
_unit_costs: dict[str, dict[str, tuple[str, int]]] = {}


@dataclass
class ModelCall:
    """One generate_content call: its token usage (None where Gemini reports none) and time."""

    prompt_tokens: int | None = None
    output_tokens: int | None = None
    thinking_tokens: int | None = None
    cached_tokens: int | None = None
    total_tokens: int | None = None
    latency_ms: int = 0


@dataclass
class SqlRun:
    """One run_sql call, as the model made it."""

    query: str
    rows: int = 0
    bytes_billed: int | None = None
    latency_ms: int = 0
    error: str | None = None


@dataclass
class RollOddsRun:
    """One roll_odds call, as the model made it. The results are not kept, only the inputs."""

    args: dict
    latency_ms: int = 0
    error: str | None = None


class UnitNeed(BaseModel):
    name: str
    copies: int
    copies_out: int = 0


class TierOut(BaseModel):
    cost: int
    copies: int


@dataclass
class Answer:
    text: str
    queries: list[str] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)
    model_calls: list[ModelCall] = field(default_factory=list)
    sql_runs: list[SqlRun] = field(default_factory=list)
    # The successful roll_odds results, for the page to show
    roll_odds: list[dict] = field(default_factory=list)
    roll_odds_runs: list[RollOddsRun] = field(default_factory=list)
    model: str = ""
    prompt_sha256: str = ""


def allowed_tables(client: bigquery.Client) -> set[str]:
    """The views, plus the tables they read.

    A dry run reports the tables a query reads with views expanded, so a query over a
    view lists the view's base tables (champion_totals, items, ...), never the view. A
    query may therefore touch only what the views already expose.
    """
    key = f"{client.project}.{DATASET}"
    if key not in _allowed:
        allowed = {table_ref(client, view) for view in prompt.VIEWS}
        for view in prompt.VIEWS:
            dry = client.query(
                f"SELECT * FROM `{table_ref(client, view)}`",
                job_config=bigquery.QueryJobConfig(dry_run=True),
            )
            allowed |= _referenced(dry)
        _allowed[key] = allowed
    return _allowed[key]


def _referenced(dry) -> set[str]:
    return {f"{t.project}.{t.dataset_id}.{t.table_id}" for t in dry.referenced_tables}


def build_context(client: bigquery.Client) -> str:
    """The system prompt: the text in prompt.py plus the views' live columns."""
    key = f"{client.project}.{DATASET}"
    if key not in _contexts:
        rows = client.query(
            f"""
            SELECT table_name, column_name, data_type
            FROM `{key}.INFORMATION_SCHEMA.COLUMNS`
            WHERE table_name IN UNNEST(@views)
            ORDER BY table_name, ordinal_position
            """,
            job_config=bigquery.QueryJobConfig(
                query_parameters=[
                    bigquery.ArrayQueryParameter("views", "STRING", prompt.VIEWS)
                ]
            ),
        ).result()
        columns: dict[str, list[str]] = {}
        for row in rows:
            columns.setdefault(row.table_name, []).append(
                f"{row.column_name} {row.data_type}"
            )
        schema = "\n".join(
            f"{view}({', '.join(cols)})" for view, cols in columns.items()
        )
        _contexts[key] = "\n\n".join(
            [
                prompt.INSTRUCTIONS.strip(),
                f"Columns:\n{prompt.GLOSSARY.strip()}",
                f"Views (query them as `{key}.<view>`):\n{schema}",
                f"Examples:\n{prompt.EXAMPLES.format(dataset=key).strip()}",
            ]
        )
    return _contexts[key]


def run_sql(
    client: bigquery.Client,
    query: str,
    log: list[str],
    runs: list[SqlRun] | None = None,
) -> list[dict]:
    """Run one guarded SELECT. Problems come back as [{"error": ...}], not exceptions.

    `log` collects the queries that were allowed to run; `runs`, if given, gets a SqlRun
    for every call, refused ones included.
    """
    run = SqlRun(query=query)
    started = time.perf_counter()
    try:
        rows = _run_guarded(client, query, log, run)
    except (exceptions.BadRequest, exceptions.Forbidden) as exc:
        rows = [{"error": str(exc)}]
    if len(rows) == 1 and "error" in rows[0]:
        run.error = str(rows[0]["error"])
    else:
        run.rows = len(rows)
    run.latency_ms = round((time.perf_counter() - started) * 1000)
    if runs is not None:
        runs.append(run)
    return rows


def _run_guarded(
    client: bigquery.Client, query: str, log: list[str], run: SqlRun
) -> list[dict]:
    dry = client.query(query, job_config=bigquery.QueryJobConfig(dry_run=True))
    if dry.statement_type != "SELECT":
        return [{"error": "Only a single SELECT statement is allowed."}]
    used = _referenced(dry)
    if not used <= allowed_tables(client):
        return [
            {
                "error": "Only these views may be queried: "
                f"{[table_ref(client, view) for view in prompt.VIEWS]}"
            }
        ]
    log.append(query)
    job = client.query(
        query,
        job_config=bigquery.QueryJobConfig(maximum_bytes_billed=MAX_BYTES_BILLED),
    )
    rows = [dict(row) for row in job.result(max_results=MAX_ROWS)]
    run.bytes_billed = getattr(job, "total_bytes_billed", None)
    return json_rows(rows)


def unit_costs(client: bigquery.Client) -> dict[str, tuple[str, int]]:
    """Every unit of the latest patch by its normalised name: (name, cost)."""
    key = f"{client.project}.{DATASET}"
    if key not in _unit_costs:
        job = client.query(
            f"SELECT name, cost FROM `{table_ref(client, 'current_champion_stats')}`",
            job_config=bigquery.QueryJobConfig(maximum_bytes_billed=MAX_BYTES_BILLED),
        )
        costs: dict[str, tuple[str, int]] = {}
        for row in job.result():
            if row["cost"] is not None:
                costs.setdefault(_normalise(row["name"]), (row["name"], int(row["cost"])))
        _unit_costs[key] = costs
    return _unit_costs[key]


def _normalise(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", name.lower())


def run_roll_odds(
    client: bigquery.Client,
    level: int,
    units: list,
    tier_out: list | None,
    gold: list[int] | None,
    answer: Answer,
) -> dict:
    """Run the roll odds calculator. Problems come back as {"error": ...}, not exceptions.

    Every call is recorded in answer.roll_odds_runs, and a successful one in answer.roll_odds,
    with the odds curve the page draws. The model gets the result without the curve.
    """
    run = RollOddsRun(
        args={"level": level, "units": units, "tier_out": tier_out, "gold": gold}
    )
    started = time.perf_counter()
    try:
        full = _roll_odds(client, level, units, tier_out, gold)
        answer.roll_odds.append(full)
        result = {key: value for key, value in full.items() if key != "curve"}
    except ValueError as exc:  # pydantic's ValidationError is one too
        run.error = str(exc)
        result = {"error": run.error}
    run.latency_ms = round((time.perf_counter() - started) * 1000)
    answer.roll_odds_runs.append(run)
    return result


def _roll_odds(client, level, units, tier_out, gold) -> dict:
    needs = [UnitNeed.model_validate(u) for u in units or []]
    gone = [TierOut.model_validate(t) for t in tier_out or []]
    costs = unit_costs(client)
    unknown = [n.name for n in needs if _normalise(n.name) not in costs]
    if unknown:
        raise ValueError(
            f"Unknown unit(s): {', '.join(unknown)}. Use these names: "
            + ", ".join(sorted(name for name, _ in costs.values()))
        )
    targets = []
    for need in needs:
        name, cost = costs[_normalise(need.name)]
        targets.append(
            roll_odds_calculator.RollTarget(name, cost, need.copies, need.copies_out)
        )
    gone_by_cost: dict[int, int] = {}
    for g in gone:
        gone_by_cost[g.cost] = gone_by_cost.get(g.cost, 0) + g.copies
    odds = roll_odds_calculator.calculate_roll_odds(
        level,
        targets,
        gold or roll_odds_calculator.DEFAULT_GOLD,
        gone_by_cost,
    )
    return {
        "level": level,
        "units": [
            {"name": t.name, "cost": t.cost, "copies": t.copies, "copies_out": t.copies_out}
            for t in targets
        ],
        "tier_out": [{"cost": c, "copies": n} for c, n in sorted(gone_by_cost.items())],
        "results": odds["results"],
        "curve": odds["curve"],
    }


def build_contents(question: str, history: list[dict] | None) -> list[types.Content]:
    """Earlier turns (only their text, last MAX_HISTORY_TURNS) followed by the question."""
    turns = (history or [])[-MAX_HISTORY_TURNS:]
    contents = [
        types.Content(role=turn["role"], parts=[types.Part(text=turn["text"])])
        for turn in turns
    ]
    contents.append(types.Content(role="user", parts=[types.Part(text=question)]))
    return contents


def model_call(response, latency_ms: int) -> ModelCall:
    usage = response.usage_metadata
    return ModelCall(
        prompt_tokens=getattr(usage, "prompt_token_count", None),
        output_tokens=getattr(usage, "candidates_token_count", None),
        thinking_tokens=getattr(usage, "thoughts_token_count", None),
        cached_tokens=getattr(usage, "cached_content_token_count", None),
        total_tokens=getattr(usage, "total_token_count", None),
        latency_ms=latency_ms,
    )


def ask(
    question: str,
    *,
    history: list[dict] | None = None,
    client: bigquery.Client | None = None,
    genai_client: genai.Client | None = None,
) -> Answer:
    """Answer one question. If it raises, the exception's `answer` attribute holds what
    was used up to that point (model calls, queries) so the caller can still account for it.
    """
    answer = Answer(text="", model=os.environ["GEMINI_SQL_MODEL"])
    try:
        _ask(question, history, client or make_client(), genai_client, answer)
    except Exception as exc:
        exc.answer = answer
        raise
    return answer


def _ask(
    question: str,
    history: list[dict] | None,
    client: bigquery.Client,
    genai_client: genai.Client | None,
    answer: Answer,
) -> None:
    genai_client = genai_client or genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    def sql(query: str) -> list[dict]:
        """Run one BigQuery SELECT over the stats views and return up to 200 rows, or [{"error": ...}] to fix and retry."""
        rows = run_sql(client, query, answer.queries, answer.sql_runs)
        if not (len(rows) == 1 and "error" in rows[0]):
            answer.rows = rows
        return rows

    def roll_odds(
        level: int,
        units: list[UnitNeed],
        tier_out: list[TierOut] | None = None,
        gold: list[int] | None = None,
    ) -> dict:
        """Odds of buying every copy a board still needs, at several amounts of gold.

        level: the player's level, 2 to 11. units: each unit the board needs, by its name, with
        copies, the copies still to buy (a 2-star needs 3 in all, a 3-star 9; subtract what is
        held), and optionally copies_out, copies of that unit already out of the pool (held by
        you or anyone else). tier_out: optionally, copies of a cost that are gone and are not
        those units' (cost and copies). gold: amounts to answer for, default 50 to 100 in 10s.
        The gold buys the copies first, and the rest rolls at 2 gold a roll. Returns per gold
        amount the rolls, all_units (the odds of every unit) and per_unit, or {"error": ...}.
        """
        return run_roll_odds(client, level, units, tier_out, gold, answer)

    tools = {"sql": sql, "roll_odds": roll_odds}

    def call_tool(call):
        fn = tools.get(call.name)
        if fn is None:
            return [{"error": f"Unknown tool {call.name}. Use one of {sorted(tools)}."}]
        args = dict(call.args or {})
        try:
            inspect.signature(fn).bind(**args)
        except TypeError as exc:
            return [{"error": f"Bad arguments for {call.name}: {exc}"}]
        return fn(**args)

    system = build_context(client)
    answer.prompt_sha256 = hashlib.sha256(system.encode()).hexdigest()
    # The loop is ours rather than the SDK's automatic function calling, which returns
    # only the last response and so hides the tokens spent on every earlier call
    config = types.GenerateContentConfig(
        system_instruction=system,
        tools=list(tools.values()),
        automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
    )
    contents = build_contents(question, history)
    for _ in range(MAX_TOOL_CALLS):
        started = time.perf_counter()
        response = genai_client.models.generate_content(
            model=answer.model, contents=contents, config=config
        )
        latency_ms = round((time.perf_counter() - started) * 1000)
        answer.model_calls.append(model_call(response, latency_ms))
        calls = response.function_calls or []
        if not calls:
            if response.text:
                answer.text = response.text
                return
            break
        contents.append(response.candidates[0].content)
        contents.append(
            types.Content(
                role="user",
                parts=[
                    types.Part.from_function_response(
                        name=call.name, response={"result": call_tool(call)}
                    )
                    for call in calls
                ],
            )
        )
    # Still calling tools (or silent) when the budget ran out
    answer.text = (
        f"No answer: the model used all {MAX_TOOL_CALLS} tool calls without finishing. "
        "Its queries are below."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("question")
    args = parser.parse_args(argv)

    answer = ask(args.question)
    print(answer.text)
    for query in answer.queries:
        print(f"\n-- SQL\n{query.strip()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Answer questions about TFT stats by letting Gemini write SQL against the stats views.

Run with `PYTHONPATH=include python -m insights.nl_to_sql "which champions are best"`.
Needs Application Default Credentials, GOOGLE_CLOUD_PROJECT, GEMINI_API_KEY and
GEMINI_SQL_MODEL (the Gemini model that writes the SQL).

The model gets two tools. `sql` (run_sql) dry-runs each query first and refuses anything
that isn't a SELECT over prompt.VIEWS or that would bill more than MAX_BYTES_BILLED.
`trios` runs a fixed query for the best 3-item builds on a champion (item_trios.py),
since those aren't kept as counters. Errors go back to the model as the tool result, so
it can fix its own call. The text the model reads lives in insights/prompt.py.
"""

import argparse
import os
import sys
from dataclasses import dataclass, field

from google import genai
from google.api_core import exceptions
from google.cloud import bigquery
from google.genai import types

from db.bq import DATASET, make_client, table_ref
from insights import prompt
from insights.common import MAX_BYTES_BILLED, MAX_ROWS, json_rows
from insights.item_trios import item_trios

MAX_TOOL_CALLS = 8

_contexts: dict[str, str] = {}
_allowed: dict[str, set[str]] = {}


@dataclass
class Answer:
    text: str
    queries: list[str] = field(default_factory=list)
    rows: list[dict] = field(default_factory=list)


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


def run_sql(client: bigquery.Client, query: str, log: list[str]) -> list[dict]:
    """Run one guarded SELECT. Problems come back as [{"error": ...}], not exceptions."""
    try:
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
    except (exceptions.BadRequest, exceptions.Forbidden) as exc:
        return [{"error": str(exc)}]
    return json_rows(rows)


def ask(
    question: str,
    *,
    client: bigquery.Client | None = None,
    genai_client: genai.Client | None = None,
) -> Answer:
    client = client or make_client()
    genai_client = genai_client or genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    answer = Answer(text="")

    def sql(query: str) -> list[dict]:
        """Run one BigQuery SELECT over the stats views and return up to 200 rows, or [{"error": ...}] to fix and retry."""
        return keep(run_sql(client, query, answer.queries))

    def trios(champion: str, min_games: int = 30) -> list[dict]:
        """The best full 3-item builds on one champion in the latest patch, best average placement first. `champion` is its name, e.g. "Kha'Zix". Use this instead of `sql` for builds of three items."""
        return keep(item_trios(client, champion, min_games, answer.queries))

    def keep(rows: list[dict]) -> list[dict]:
        if not (len(rows) == 1 and "error" in rows[0]):
            answer.rows = rows
        return rows

    response = genai_client.models.generate_content(
        model=os.environ["GEMINI_SQL_MODEL"],
        contents=question,
        config=types.GenerateContentConfig(
            system_instruction=build_context(client),
            tools=[sql, trios],
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                maximum_remote_calls=MAX_TOOL_CALLS
            ),
        ),
    )
    # No text means the model was still calling tools when it hit MAX_TOOL_CALLS
    answer.text = response.text or (
        f"No answer: the model used all {MAX_TOOL_CALLS} tool calls without finishing. "
        "Its queries are below."
    )
    return answer


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

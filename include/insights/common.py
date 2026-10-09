"""Limits and helpers shared by the SQL agent's tools."""

import json

MAX_BYTES_BILLED = 1_000_000_000
MAX_ROWS = 200


def json_rows(rows: list[dict]) -> list[dict]:
    """Rows with dates, Decimals and the like as strings, so they can go to the model and a UI."""
    return json.loads(json.dumps(rows, default=str))

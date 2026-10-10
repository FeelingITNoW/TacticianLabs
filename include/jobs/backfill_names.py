"""Fill participant_units.champion_name, unit_items.item_name and participants'
completed_items/board_cost from the reference tables.

Run with `python -m jobs.backfill_names` (PYTHONPATH must include `include/`).

The ingest fills these as it writes, so this is for rows written before the columns
existed or before their champion/item was seeded, and for names, costs and item types
changed by a reseed (db.seed_reference_data runs it too). It only rewrites rows whose
value is missing or stale, but scans the whole of each table. --table limits it to the
named tables.
"""

import argparse
import sys

from db.bq import make_client
from db.reference_names import BACKFILL_TABLES, backfill_names


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--table",
        action="append",
        choices=list(BACKFILL_TABLES),
        help="only this table (repeatable); default every table",
    )
    args = parser.parse_args(argv)

    tables = args.table or list(BACKFILL_TABLES)
    backfill_names(make_client(), tables)
    print(f"Backfilled {', '.join(tables)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

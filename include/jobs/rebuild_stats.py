"""Recompute the per-patch totals tables from the match tables.

Run with `python -m jobs.rebuild_stats` (PYTHONPATH must include `include/`).

The ingest keeps the totals current incrementally, so this is only for the first
backfill after the totals tables are created and for recovery. With --check it
writes nothing: it recounts and reports every totals table that disagrees, and exits
1 if there are any.

By default it covers every totals table and every patch, which scans all the match
tables. --table limits it to the named tables, and --patch (a game version, or
`latest`) to one patch, which only reads that patch's days. For example, to fill a
new totals table for the current patch:

    python -m jobs.rebuild_stats --table champion_item_pair_totals --patch latest
"""

import argparse
import sys

from data_aggregation.data_aggregation import (
    TOTALS,
    check_totals,
    latest_patch,
    rebuild_totals,
)
from db.bq import make_client


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare the totals with a fresh recount instead of rebuilding them",
    )
    parser.add_argument(
        "--table",
        action="append",
        choices=list(TOTALS),
        help="only this totals table (repeatable); default every table",
    )
    parser.add_argument(
        "--patch",
        help="only this patch (a game version, or 'latest'); default every patch",
    )
    args = parser.parse_args(argv)

    client = make_client()
    patch = args.patch
    if patch == "latest":
        patch = latest_patch(client)
        if patch is None:
            print("No patches yet: patch_totals is empty")
            return 1
    scope = ", ".join(args.table) if args.table else "every totals table"
    scope += f" for patch {patch}" if patch else ""

    try:
        if not args.check:
            rebuild_totals(client, args.table, patch)
            print(f"Rebuilt {scope}")
            return 0

        mismatches = check_totals(client, args.table, patch)
    except ValueError as exc:
        print(exc)
        return 1
    for table, count in mismatches.items():
        print(f"{table}: {count} mismatched rows")
    return 1 if any(mismatches.values()) else 0


if __name__ == "__main__":
    sys.exit(main())

"""Recompute the per-patch totals tables from the match tables.

Run with `python -m jobs.rebuild_stats` (PYTHONPATH must include `include/`).

The ingest keeps the totals current incrementally, so this is only for the first
backfill after the totals tables are created and for recovery. With --check it
writes nothing: it recounts and reports every totals row that disagrees, and exits
1 if there are any.
"""

import argparse
import sys

from data_aggregation.data_aggregation import check_totals, rebuild_totals
from db.bq import make_client


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--check",
        action="store_true",
        help="compare the totals with a fresh recount instead of rebuilding them",
    )
    args = parser.parse_args(argv)

    client = make_client()
    if not args.check:
        rebuild_totals(client)
        print("Rebuilt every totals table")
        return 0

    mismatches = check_totals(client)
    for table, count in mismatches.items():
        print(f"{table}: {count} mismatched rows")
    return 1 if any(mismatches.values()) else 0


if __name__ == "__main__":
    sys.exit(main())

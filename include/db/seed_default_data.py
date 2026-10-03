"""Seed BigQuery with the default dataset: Set 18 reference data plus the matches
archived under tft/matches/16.19.1/2026-09-28/ in GCS.

Safe to re-run; it also works as "reset to the known default data".

Usage:
    PYTHONPATH=include python -m db.seed_default_data [--skip-embeddings] [--limit N]
"""

import sys

from dotenv import load_dotenv

from db.bq import make_client
from db.seed_reference_data import seed_reference_data
from jobs.load_gcs_matches import DEFAULT_PREFIX, build_parser, main as load_main

if __name__ == "__main__":
    load_dotenv()
    args = build_parser().parse_args()
    if args.prefix != DEFAULT_PREFIX:
        sys.exit("Use python -m jobs.load_gcs_matches to load a different prefix.")
    seed_reference_data(make_client())
    sys.exit(load_main(sys.argv[1:]))

"""Load archived match JSON from GCS into BigQuery.

Run with `python -m jobs.load_gcs_matches` (PYTHONPATH must include `include/`).

Reads every match under one archive prefix, tft/matches/<ddragon_version>/<date>/
(the layout written by gcs_bucket_api.upload_to_bucket), and writes it with the same
code the daily ingest uses. Writes are idempotent. Matches already in BigQuery are
skipped unless --reload is given, which also saves their Gemini calls.
"""

import argparse
import os
import re
import sys
from concurrent.futures import ThreadPoolExecutor

from google import genai
from google.cloud import bigquery, storage

from db.bq import make_client
from db.parse_match_data import filter_new_match_ids, write_matches

DEFAULT_PREFIX = "tft/matches/16.19.1/2026-09-28/"
CHUNK_SIZE = 50
DOWNLOAD_THREADS = 16

_PREFIX_RE = re.compile(r"^tft/matches/(?P<version>[^/]+)/(?P<date>\d{4}-\d{2}-\d{2})/$")


def parse_prefix(prefix: str) -> tuple[str, str]:
    """Return (ddragon_version, date) for a tft/matches/<version>/<date>/ prefix."""
    match = _PREFIX_RE.match(prefix)
    if match is None:
        raise ValueError(
            f"Prefix {prefix!r} must look like tft/matches/<version>/<YYYY-MM-DD>/"
        )
    return match["version"], match["date"]


def default_bucket() -> str:
    return os.getenv("GCS_BUCKET") or f"{make_client().project}-tft-match-data"


def load_prefix(
    bq_client: bigquery.Client,
    storage_client,
    genai_client: genai.Client | None,
    bucket: str,
    prefix: str = DEFAULT_PREFIX,
    limit: int | None = None,
    reload: bool = False,
) -> tuple[int, int]:
    """Load one archive prefix. Returns (ingested, failed)."""
    version, _ = parse_prefix(prefix)
    blobs = {
        blob.name.rsplit("/", 1)[1].removesuffix(".json"): blob
        for blob in storage_client.list_blobs(bucket, prefix=prefix)
        if blob.name.endswith(".json")
    }
    match_ids = sorted(blobs)
    if not reload:
        match_ids = filter_new_match_ids(bq_client, match_ids)
    if limit is not None:
        match_ids = match_ids[:limit]
    print(f"{len(match_ids)} of {len(blobs)} matches to load from {prefix}")

    ingested = failed = 0
    with ThreadPoolExecutor(DOWNLOAD_THREADS) as pool:
        for start in range(0, len(match_ids), CHUNK_SIZE):
            chunk = match_ids[start : start + CHUNK_SIZE]
            try:
                bodies = dict(
                    zip(chunk, pool.map(lambda m: blobs[m].download_as_text(), chunk))
                )
                written, bad = write_matches(bq_client, bodies, version, genai_client)
            except Exception as exc:
                failed += len(chunk)
                print(f"Chunk starting at {start} failed: {exc!r}")
                continue
            ingested += written
            failed += bad
            print(f"{start + len(chunk)}/{len(match_ids)} processed")
    print(f"Loaded {ingested} matches, {failed} failures")
    return ingested, failed


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--prefix", default=DEFAULT_PREFIX)
    parser.add_argument("--bucket", default=None)
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--reload", action="store_true")
    parser.add_argument(
        "--skip-embeddings",
        action="store_true",
        help="leave participants.embedding empty (no Gemini calls)",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    genai_client = (
        None
        if args.skip_embeddings
        else genai.Client(api_key=os.environ["GEMINI_API_KEY"])
    )
    _, failed = load_prefix(
        make_client(),
        storage.Client(),
        genai_client,
        args.bucket or default_bucket(),
        prefix=args.prefix,
        limit=args.limit,
        reload=args.reload,
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

"""Read the /ask conversation logs: `PYTHONPATH=include python -m insights.conversations`.

    list [--limit N]   the most recently updated conversations, newest first
    show <uuid>        one conversation as JSON

Needs ASK_LOG_BUCKET and read access to it (Application Default Credentials).
"""

import argparse
import json
import os
import sys

from insights.conversation_log import PREFIX, blob_name


def summary(blob) -> str:
    document = json.loads(blob.download_as_bytes())
    turns = document["turns"]
    tokens = sum(t.get("tokens") or 0 for t in turns)
    failed = sum(1 for t in turns if t.get("error"))
    first = turns[0]["question"].replace("\n", " ")[:60] if turns else ""
    return (
        f"{document['conversation_id']}  {document['updated_at'][:19]}  "
        f"{len(turns):>2} turns  {tokens:>8} tokens  {failed} failed  {first}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    list_parser = commands.add_parser("list")
    list_parser.add_argument("--limit", type=int, default=20)
    show_parser = commands.add_parser("show")
    show_parser.add_argument("conversation_id")
    args = parser.parse_args(argv)

    from google.cloud import storage

    bucket_name = os.environ.get("ASK_LOG_BUCKET")
    if not bucket_name:
        raise SystemExit("Set ASK_LOG_BUCKET")
    bucket = storage.Client().bucket(bucket_name)

    if args.command == "show":
        blob = bucket.get_blob(blob_name(args.conversation_id))
        if blob is None:
            raise SystemExit(f"No conversation {args.conversation_id}")
        print(blob.download_as_text())
        return 0

    blobs = sorted(
        bucket.list_blobs(prefix=PREFIX), key=lambda b: b.updated, reverse=True
    )
    for blob in blobs[: args.limit]:
        print(summary(blob))
    return 0


if __name__ == "__main__":
    sys.exit(main())

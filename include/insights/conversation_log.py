"""Log /ask conversations to Cloud Storage, one JSON object per conversation.

Object `conversations/<uuid>.json` holds {conversation_id, started_at, updated_at, turns}.
GCS objects can't be appended to, so each turn reads the object, adds the turn and writes
it back with a generation precondition; a concurrent write for the same conversation makes
the loser re-read and try again. Needs ASK_LOG_BUCKET (insights/server.py leaves logging
off without it). Read the logs back with `python -m insights.conversations`.
"""

import json
import logging
from dataclasses import asdict
from datetime import UTC, datetime

from google.api_core import exceptions

PREFIX = "conversations/"
WRITE_ATTEMPTS = 3

log = logging.getLogger("insights.conversation_log")


def blob_name(conversation_id: str) -> str:
    return f"{PREFIX}{conversation_id}.json"


def _sum(calls: list, attribute: str) -> int | None:
    values = [getattr(c, attribute) for c in calls if getattr(c, attribute) is not None]
    return sum(values) if values else None


def turn_record(
    question: str,
    *,
    history_turns: int,
    answer,
    error: str | None,
    latency_ms: int,
    started_at: datetime,
) -> dict:
    """One turn of a conversation. `answer` may be partial (or None) when the turn failed.

    `tokens` is the total over every model call of the turn and `prompt_tokens` the
    prompt side of it (the prompt is sent again with each tool round, so it adds up).
    """
    calls = list(getattr(answer, "model_calls", None) or [])
    return {
        "started_at": started_at.astimezone(UTC).isoformat(),
        "question": question,
        "answer": getattr(answer, "text", None) or None,
        "error": error,
        "history_turns": history_turns,
        "model": getattr(answer, "model", None) or None,
        "system_prompt_sha256": getattr(answer, "prompt_sha256", None) or None,
        "latency_ms": latency_ms,
        "tokens": _sum(calls, "total_tokens"),
        "prompt_tokens": _sum(calls, "prompt_tokens"),
        "output_tokens": _sum(calls, "output_tokens"),
        "thinking_tokens": _sum(calls, "thinking_tokens"),
        "cached_tokens": _sum(calls, "cached_tokens"),
        "model_calls": [asdict(c) for c in calls],
        "sql_runs": [asdict(r) for r in getattr(answer, "sql_runs", None) or []],
    }


def append_turn(bucket, conversation_id: str, turn: dict) -> None:
    """Add `turn` to the conversation's object, creating it on the first turn."""
    name = blob_name(conversation_id)
    for attempt in range(WRITE_ATTEMPTS):
        existing = bucket.get_blob(name)
        if existing is None:
            blob, generation = bucket.blob(name), 0
            document = {
                "conversation_id": conversation_id,
                "started_at": turn["started_at"],
                "turns": [],
            }
        else:
            blob, generation = existing, existing.generation
            document = json.loads(existing.download_as_bytes())
        document["updated_at"] = datetime.now(UTC).isoformat()
        document["turns"].append({"turn": len(document["turns"]) + 1, **turn})
        try:
            blob.upload_from_string(
                json.dumps(document, indent=2),
                content_type="application/json",
                if_generation_match=generation,
            )
            return
        except exceptions.PreconditionFailed:
            if attempt == WRITE_ATTEMPTS - 1:
                raise
            log.info("conversation %s changed under us, retrying", conversation_id)

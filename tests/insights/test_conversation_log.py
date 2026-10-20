"""Tests for the conversation log (include/insights/conversation_log.py)."""

import json
from datetime import UTC, datetime

import pytest
from google.api_core import exceptions

from insights import conversation_log
from insights.nl_to_sql import Answer, ModelCall, SqlRun

ID = "0b1f6a0e-6a4e-4c53-9d5b-1c2a3b4c5d6e"
NAME = f"conversations/{ID}.json"


class FakeBlob:
    def __init__(self, bucket, name, content=None, generation=0):
        self.bucket, self.name = bucket, name
        self.content, self.generation = content, generation

    def download_as_bytes(self):
        return self.content

    def upload_from_string(self, data, content_type, if_generation_match):
        assert content_type == "application/json"
        if self.bucket.fail_next:
            self.bucket.fail_next -= 1
            raise exceptions.PreconditionFailed("changed")
        stored = self.bucket.objects.get(self.name)
        assert if_generation_match == (stored[1] if stored else 0)
        self.bucket.objects[self.name] = (data.encode(), if_generation_match + 1)


class FakeBucket:
    def __init__(self, fail_next=0):
        self.objects: dict[str, tuple[bytes, int]] = {}
        self.fail_next = fail_next

    def get_blob(self, name):
        if name not in self.objects:
            return None
        content, generation = self.objects[name]
        return FakeBlob(self, name, content, generation)

    def blob(self, name):
        return FakeBlob(self, name)


def turn(question="q", **extra):
    started = datetime(2026, 10, 19, tzinfo=UTC)
    return conversation_log.turn_record(
        question,
        history_turns=0,
        answer=Answer(text="a"),
        error=None,
        latency_ms=5,
        started_at=started,
    ) | extra


def test_turn_record_sums_every_model_call():
    answer = Answer(
        text="done",
        model="gemini-x",
        prompt_sha256="abc",
        model_calls=[
            ModelCall(prompt_tokens=100, output_tokens=5, total_tokens=105, latency_ms=10),
            ModelCall(prompt_tokens=150, output_tokens=20, total_tokens=170, latency_ms=20),
        ],
        sql_runs=[SqlRun(query="SELECT 1", rows=1, bytes_billed=10, latency_ms=4)],
    )

    record = conversation_log.turn_record(
        "q",
        history_turns=2,
        answer=answer,
        error=None,
        latency_ms=99,
        started_at=datetime(2026, 10, 19, tzinfo=UTC),
    )

    assert record["tokens"] == 275
    assert record["prompt_tokens"] == 250
    assert record["output_tokens"] == 25
    assert record["thinking_tokens"] is None  # never reported
    assert record["latency_ms"] == 99 and record["history_turns"] == 2
    assert record["sql_runs"][0]["bytes_billed"] == 10
    assert len(record["model_calls"]) == 2
    assert record["started_at"] == "2026-10-19T00:00:00+00:00"


def test_turn_record_without_an_answer():
    record = conversation_log.turn_record(
        "q",
        history_turns=0,
        answer=None,
        error="boom",
        latency_ms=1,
        started_at=datetime(2026, 10, 19, tzinfo=UTC),
    )

    assert record["answer"] is None and record["tokens"] is None
    assert record["model_calls"] == [] and record["error"] == "boom"


def test_first_turn_creates_the_object_and_later_turns_append():
    bucket = FakeBucket()

    conversation_log.append_turn(bucket, ID, turn("first"))
    conversation_log.append_turn(bucket, ID, turn("second"))

    document = json.loads(bucket.objects[NAME][0])
    assert document["conversation_id"] == ID
    assert [t["question"] for t in document["turns"]] == ["first", "second"]
    assert [t["turn"] for t in document["turns"]] == [1, 2]
    assert bucket.objects[NAME][1] == 2  # written twice, each against the last generation


def test_retries_after_a_concurrent_write():
    bucket = FakeBucket(fail_next=1)

    conversation_log.append_turn(bucket, ID, turn())

    assert len(json.loads(bucket.objects[NAME][0])["turns"]) == 1


def test_gives_up_after_repeated_conflicts():
    bucket = FakeBucket(fail_next=conversation_log.WRITE_ATTEMPTS)

    with pytest.raises(exceptions.PreconditionFailed):
        conversation_log.append_turn(bucket, ID, turn())

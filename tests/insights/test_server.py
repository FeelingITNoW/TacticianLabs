"""Tests for the agent's HTTP request handling (include/insights/server.py)."""

import json
from types import SimpleNamespace

from insights.nl_to_sql import Answer, ModelCall
from insights.server import handle_ask

CONVERSATION = "0b1f6a0e-6a4e-4c53-9d5b-1c2a3b4c5d6e"


def fake_ask(question, history):
    return SimpleNamespace(text=f"{question}|{len(history)}", queries=["SELECT 1"])


def test_happy_path():
    status, body, write_log = handle_ask(
        {"question": " best Taric build? ", "history": [{"role": "user", "text": "a"}]},
        fake_ask,
    )

    assert status == 200
    assert body == {"text": "best Taric build?|1", "queries": ["SELECT 1"]}
    assert write_log is None  # no conversation_id, nothing to log


def test_rejects_bad_input():
    bad = [
        None,
        {},
        {"question": ""},
        {"question": "x" * 501},
        {"question": "q", "history": "no"},
        {"question": "q", "history": [{"role": "system", "text": "a"}]},
        {"question": "q", "history": [{"role": "user", "text": "a"}] * 13},
        {"question": "q", "conversation_id": "../../etc/passwd"},
        {"question": "q", "conversation_id": CONVERSATION.upper()},
        {"question": "q", "conversation_id": 5},
    ]
    for payload in bad:
        status, _, write_log = handle_ask(payload, fake_ask)
        assert status == 400 and write_log is None


def test_failure_is_a_generic_500():
    def boom(question, history):
        raise RuntimeError("SELECT secret FROM x")

    status, body, _ = handle_ask({"question": "q"}, boom)

    assert status == 500
    assert "secret" not in str(body)


class FakeBucket:
    def __init__(self):
        self.blobs = {}

    def get_blob(self, name):
        return None

    def blob(self, name):
        bucket = self

        class Blob:
            def upload_from_string(self, data, content_type, if_generation_match):
                bucket.blobs[name] = (data, if_generation_match)

        return Blob()


def test_logs_a_turn_when_there_is_a_conversation_id():
    def ask(question, history):
        return Answer(
            text="answer",
            model_calls=[ModelCall(prompt_tokens=10, total_tokens=15, latency_ms=3)],
        )

    status, _, write_log = handle_ask(
        {"question": "q", "conversation_id": CONVERSATION}, ask
    )
    bucket = FakeBucket()
    write_log(bucket)

    assert status == 200
    data, generation = bucket.blobs[f"conversations/{CONVERSATION}.json"]
    turn = json.loads(data)["turns"][0]
    assert generation == 0
    assert (turn["question"], turn["answer"], turn["tokens"]) == ("q", "answer", 15)
    assert turn["prompt_tokens"] == 10 and turn["error"] is None


def test_a_failed_turn_is_logged_with_what_it_used():
    def boom(question, history):
        exc = RuntimeError("model fell over")
        exc.answer = Answer(text="", model_calls=[ModelCall(total_tokens=7)])
        raise exc

    status, _, write_log = handle_ask(
        {"question": "q", "conversation_id": CONVERSATION}, boom
    )
    bucket = FakeBucket()
    write_log(bucket)

    turn = json.loads(bucket.blobs[f"conversations/{CONVERSATION}.json"][0])["turns"][0]
    assert status == 500
    assert turn["error"] == "RuntimeError: model fell over"
    assert turn["answer"] is None and turn["tokens"] == 7

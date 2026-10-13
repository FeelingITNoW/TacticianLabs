"""Tests for the agent's HTTP request handling (include/insights/server.py)."""

from types import SimpleNamespace

from insights.server import handle_ask


def fake_ask(question, history):
    return SimpleNamespace(text=f"{question}|{len(history)}", queries=["SELECT 1"])


def test_happy_path():
    status, body = handle_ask(
        {"question": " best Taric build? ", "history": [{"role": "user", "text": "a"}]},
        fake_ask,
    )

    assert status == 200
    assert body == {"text": "best Taric build?|1", "queries": ["SELECT 1"]}


def test_rejects_bad_input():
    bad = [
        None,
        {},
        {"question": ""},
        {"question": "x" * 501},
        {"question": "q", "history": "no"},
        {"question": "q", "history": [{"role": "system", "text": "a"}]},
        {"question": "q", "history": [{"role": "user", "text": "a"}] * 13},
    ]
    for payload in bad:
        assert handle_ask(payload, fake_ask)[0] == 400


def test_failure_is_a_generic_500():
    def boom(question, history):
        raise RuntimeError("SELECT secret FROM x")

    status, body = handle_ask({"question": "q"}, boom)

    assert status == 500
    assert "secret" not in str(body)

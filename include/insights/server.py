"""HTTP service the web app's /ask page calls: `PYTHONPATH=include python -m insights.server`.

POST /ask {"question": str, "history": [{"role": "user"|"model", "text": str}],
"conversation_id": uuid, optional} returns {"text": str, "queries": [str]}. With a
conversation_id and ASK_LOG_BUCKET set, each turn (also a failed one) is appended to that
conversation's log in Cloud Storage after the response is sent (see conversation_log).
It is long-lived so the schema and
allowed-table caches in nl_to_sql stay warm. Needs the same environment as nl_to_sql, and binds to
AGENT_HOST (default 127.0.0.1) and AGENT_PORT (default PORT, which hosts such as Railway
set, else 8001). Without gcloud, set GOOGLE_CREDENTIALS_JSON to the agent service
account key (BigQuery read-only, write on the log bucket); AGENT_HOST=:: listens on IPv4 and IPv6 (Railway's private network).
"""

import json
import logging
import os
import socket
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from insights import conversation_log

MAX_QUESTION = 500
MAX_HISTORY = 12
MAX_TURN_TEXT = 8000
MAX_BODY = 200_000

log = logging.getLogger("insights.server")


def validate(payload) -> tuple[str, list[dict], str | None]:
    """The question, history and conversation id of a request, or ValueError saying what is wrong."""
    if not isinstance(payload, dict):
        raise ValueError("Body must be a JSON object")
    question = payload.get("question")
    if not isinstance(question, str) or not 1 <= len(question.strip()) <= MAX_QUESTION:
        raise ValueError(f"question must be 1 to {MAX_QUESTION} characters")
    history = payload.get("history", [])
    if not isinstance(history, list) or len(history) > MAX_HISTORY:
        raise ValueError(f"history must be a list of at most {MAX_HISTORY} turns")
    turns = []
    for turn in history:
        if (
            not isinstance(turn, dict)
            or turn.get("role") not in ("user", "model")
            or not isinstance(turn.get("text"), str)
            or not 1 <= len(turn["text"]) <= MAX_TURN_TEXT
        ):
            raise ValueError("each history turn needs a role (user or model) and text")
        turns.append({"role": turn["role"], "text": turn["text"]})
    conversation_id = payload.get("conversation_id")
    if conversation_id is not None:
        try:
            canonical = str(uuid.UUID(conversation_id))
        except (ValueError, AttributeError, TypeError):
            canonical = None
        # It ends up in an object name, so only the canonical lowercase form passes
        if canonical != conversation_id:
            raise ValueError("conversation_id must be a lowercase UUID")
    return question.strip(), turns, conversation_id


def handle_ask(payload, ask_fn: Callable) -> tuple[int, dict, Callable | None]:
    """Status and JSON body for one request, and a function that logs the turn (None when
    the request has no conversation_id). Failures never leak SQL or tracebacks.
    """
    try:
        question, history, conversation_id = validate(payload)
    except ValueError as exc:
        return 400, {"error": str(exc)}, None
    started_at = datetime.now(UTC)
    started = time.perf_counter()
    answer, error = None, None
    try:
        answer = ask_fn(question, history=history)
        status, body = 200, {"text": answer.text, "queries": answer.queries}
    except Exception as exc:
        log.exception("agent failed")
        answer = getattr(exc, "answer", None)  # what the agent had used up
        error = f"{type(exc).__name__}: {exc}"
        status, body = 500, {"error": "The agent failed"}
    if conversation_id is None:
        return status, body, None
    turn = conversation_log.turn_record(
        question,
        history_turns=len(history),
        answer=answer,
        error=error,
        latency_ms=round((time.perf_counter() - started) * 1000),
        started_at=started_at,
    )
    return status, body, lambda bucket: conversation_log.append_turn(
        bucket, conversation_id, turn
    )


def make_handler(ask_fn: Callable, bucket=None) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, body: dict) -> None:
            data = json.dumps(body).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/healthz":
                self._send(200, {"ok": True})
            else:
                self._send(404, {"error": "Not found"})

        def do_POST(self):
            if self.path != "/ask":
                return self._send(404, {"error": "Not found"})
            try:
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length <= MAX_BODY:
                    return self._send(400, {"error": "Body missing or too large"})
                payload = json.loads(self.rfile.read(length))
            except ValueError:
                return self._send(400, {"error": "Body must be JSON"})
            status, body, write_log = handle_ask(payload, ask_fn)
            self._send(status, body)
            # After the response, so logging adds no latency; a failure only costs the log
            if write_log is not None and bucket is not None:
                try:
                    write_log(bucket)
                except Exception:
                    log.exception("could not log the conversation")

        def log_message(self, format, *args):
            log.info("%s %s", self.address_string(), format % args)

    return Handler


class DualStackServer(ThreadingHTTPServer):
    """Listens on IPv4 and IPv6 at once, for AGENT_HOST=::"""

    address_family = socket.AF_INET6

    def server_bind(self):
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()


def _service_account():
    """(credentials, project) from the key in GOOGLE_CREDENTIALS_JSON, or None to use
    Application Default Credentials."""
    raw = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if not raw:
        return None
    from google.oauth2 import service_account

    info = json.loads(raw)
    credentials = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    return credentials, os.getenv("GOOGLE_CLOUD_PROJECT") or info.get("project_id")


def make_bigquery_client():
    """A key in GOOGLE_CREDENTIALS_JSON if set, else Application Default Credentials."""
    account = _service_account()
    if account is None:
        from db.bq import make_client

        return make_client()
    from google.cloud import bigquery

    credentials, project = account
    return bigquery.Client(project=project, credentials=credentials)


def make_log_bucket():
    """The ASK_LOG_BUCKET bucket, or None (conversations are then not logged)."""
    name = os.environ.get("ASK_LOG_BUCKET")
    if not name:
        return None
    from google.cloud import storage

    account = _service_account()
    if account is None:
        return storage.Client().bucket(name)
    credentials, project = account
    return storage.Client(project=project, credentials=credentials).bucket(name)


def main() -> None:
    from google import genai

    from insights import nl_to_sql

    logging.basicConfig(level=logging.INFO)
    for name in ("GEMINI_API_KEY", "GEMINI_SQL_MODEL"):
        if not os.environ.get(name):
            raise SystemExit(f"Set {name}")
    client = make_bigquery_client()
    genai_client = genai.Client(api_key=os.environ["GEMINI_API_KEY"])

    def ask_fn(question: str, history: list[dict]):
        return nl_to_sql.ask(
            question, history=history, client=client, genai_client=genai_client
        )

    bucket = make_log_bucket()
    log.info("Logging conversations to %s", bucket.name if bucket else "nowhere")
    host = os.environ.get("AGENT_HOST", "127.0.0.1")
    port = int(os.environ.get("AGENT_PORT") or os.environ.get("PORT") or 8001)
    server_class = DualStackServer if ":" in host else ThreadingHTTPServer
    log.info("Agent listening on %s:%s", host, port)
    server_class((host, port), make_handler(ask_fn, bucket)).serve_forever()


if __name__ == "__main__":
    main()

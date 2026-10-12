"""HTTP service the web app's /ask page calls: `PYTHONPATH=include python -m insights.server`.

POST /ask {"question": str, "history": [{"role": "user"|"model", "text": str}]}
returns {"text": str, "queries": [str]}. It is long-lived so the schema and allowed-table
caches in nl_to_sql stay warm. Needs the same environment as nl_to_sql, and binds to
AGENT_HOST (default 127.0.0.1) and AGENT_PORT (default PORT, which hosts such as Railway
set, else 8001). Without gcloud, set GOOGLE_CREDENTIALS_JSON to a read-only service
account key; AGENT_HOST=:: listens on IPv4 and IPv6 (Railway's private network).
"""

import json
import logging
import os
import socket
from collections.abc import Callable
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

MAX_QUESTION = 500
MAX_HISTORY = 12
MAX_TURN_TEXT = 8000
MAX_BODY = 200_000

log = logging.getLogger("insights.server")


def validate(payload) -> tuple[str, list[dict]]:
    """The question and history of a request, or ValueError saying what is wrong."""
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
    return question.strip(), turns


def handle_ask(payload, ask_fn: Callable) -> tuple[int, dict]:
    """Status and JSON body for one request. Failures never leak SQL or tracebacks."""
    try:
        question, history = validate(payload)
    except ValueError as exc:
        return 400, {"error": str(exc)}
    try:
        answer = ask_fn(question, history=history)
    except Exception:
        log.exception("agent failed")
        return 500, {"error": "The agent failed"}
    return 200, {"text": answer.text, "queries": answer.queries}


def make_handler(ask_fn: Callable) -> type[BaseHTTPRequestHandler]:
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
            self._send(*handle_ask(payload, ask_fn))

        def log_message(self, format, *args):
            log.info("%s %s", self.address_string(), format % args)

    return Handler


class DualStackServer(ThreadingHTTPServer):
    """Listens on IPv4 and IPv6 at once, for AGENT_HOST=::"""

    address_family = socket.AF_INET6

    def server_bind(self):
        self.socket.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)
        super().server_bind()


def make_bigquery_client():
    """A key in GOOGLE_CREDENTIALS_JSON if set, else Application Default Credentials."""
    raw = os.environ.get("GOOGLE_CREDENTIALS_JSON")
    if not raw:
        from db.bq import make_client

        return make_client()
    from google.cloud import bigquery
    from google.oauth2 import service_account

    info = json.loads(raw)
    credentials = service_account.Credentials.from_service_account_info(
        info, scopes=["https://www.googleapis.com/auth/cloud-platform"]
    )
    project = os.getenv("GOOGLE_CLOUD_PROJECT") or info.get("project_id")
    return bigquery.Client(project=project, credentials=credentials)


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

    host = os.environ.get("AGENT_HOST", "127.0.0.1")
    port = int(os.environ.get("AGENT_PORT") or os.environ.get("PORT") or 8001)
    server_class = DualStackServer if ":" in host else ThreadingHTTPServer
    log.info("Agent listening on %s:%s", host, port)
    server_class((host, port), make_handler(ask_fn)).serve_forever()


if __name__ == "__main__":
    main()

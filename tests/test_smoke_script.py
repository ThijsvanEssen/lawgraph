"""``scripts/smoke.sh`` against a small local server: the routes pass, and the version that
``/api/health`` names is compared with the one expected."""

from __future__ import annotations

import json
import subprocess
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SMOKE = Path(__file__).resolve().parents[1] / "scripts" / "smoke.sh"


def _server(health: dict) -> ThreadingHTTPServer:
    body = json.dumps(health, separators=(",", ":")).encode()

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            payload = body if self.path == "/api/health" else b"{}"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args: object) -> None:
            pass

    return ThreadingHTTPServer(("127.0.0.1", 0), Handler)


@pytest.fixture
def serve() -> Iterator:
    servers: list[ThreadingHTTPServer] = []

    def start(health: dict) -> str:
        server = _server(health)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        servers.append(server)
        return f"http://127.0.0.1:{server.server_address[1]}"

    yield start
    for server in servers:
        server.shutdown()
        server.server_close()


def _smoke(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["sh", str(SMOKE), *args],
        env={"PATH": "/usr/bin:/bin:/usr/local/bin", "RETRY_SECONDS": "0"},
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_the_expected_version_passes(serve) -> None:
    run = _smoke(serve({"status": "ok", "version": "1.2.3"}), "1.2.3")
    assert run.returncode == 0, run.stdout
    assert "ok   version 1.2.3" in run.stdout


def test_another_version_fails(serve) -> None:
    run = _smoke(serve({"status": "ok", "version": "1.2.2"}), "1.2.3")
    assert run.returncode == 1
    assert "FAIL version: 1.2.2 live, 1.2.3 expected" in run.stdout


def test_a_health_without_version_fails_when_one_is_expected(serve) -> None:
    run = _smoke(serve({"status": "ok"}), "1.2.3")
    assert run.returncode == 1
    assert "FAIL version" in run.stdout


def test_without_an_expected_version_only_the_routes_count(serve) -> None:
    run = _smoke(serve({"status": "ok", "version": "1.2.3"}))
    assert run.returncode == 0, run.stdout
    assert "version" not in run.stdout

"""A query that runs past ``LAWGRAPH_READ_TIMEOUT_MS`` answers 503 with ``Retry-After``:
the server is busy, not broken, and the statement stays in the log."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import READ_TIMEOUT_RETRY_AFTER, app
from lawgraph.api.routes import government
from lawgraph.db.store import ReadTimedOut


def test_a_read_past_its_ceiling_is_a_503_with_retry_after(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def too_long(store):
        raise ReadTimedOut("A read ran for over 0 minutes: SELECT secret_statement")

    monkeypatch.setattr(government, "get_cabinets", too_long)
    with caplog.at_level("WARNING"):
        response = TestClient(app, raise_server_exceptions=False).get("/api/cabinets")

    assert response.status_code == 503
    assert response.headers["retry-after"] == str(READ_TIMEOUT_RETRY_AFTER)
    assert response.json() == {
        "detail": "The query took too long. Try again later, or narrow it."
    }
    assert "secret_statement" not in response.text
    assert any("secret_statement" in m for m in caplog.messages)


def test_the_reads_of_a_request_share_one_deadline(monkeypatch) -> None:
    """Each statement of a request gets what the request has left, not a ceiling of its own;
    a read with nothing left is a 503 before it reaches the database."""
    from lawgraph.db import store as store_module

    seen: list[int] = []

    def two_reads(store):
        seen.append(store_module._read_budget_ms())
        import time as clock

        clock.sleep(0.15)
        seen.append(store_module._read_budget_ms())
        return []

    monkeypatch.setattr("lawgraph.api.app.API_REQUEST_TIMEOUT_MS", 1000)
    monkeypatch.setattr(store_module, "READ_TIMEOUT_MS", 600_000)
    monkeypatch.setattr(government, "get_cabinets", two_reads)
    response = TestClient(app, raise_server_exceptions=False).get("/api/cabinets")
    assert response.status_code == 200
    assert 800 < seen[0] <= 1000 and seen[1] <= seen[0] - 100

    def past(store):
        import time as clock

        clock.sleep(0.25)
        store_module._read_budget_ms()
        return []

    monkeypatch.setattr("lawgraph.api.app.API_REQUEST_TIMEOUT_MS", 200)
    monkeypatch.setattr(government, "get_cabinets", past)
    response = TestClient(app, raise_server_exceptions=False).get("/api/cabinets")
    assert response.status_code == 503


def test_outside_a_request_a_read_has_the_ceiling_alone(monkeypatch) -> None:
    from lawgraph.db import store as store_module

    monkeypatch.setattr(store_module, "READ_TIMEOUT_MS", 1234)
    assert store_module._read_budget_ms() == 1234

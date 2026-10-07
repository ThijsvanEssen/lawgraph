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

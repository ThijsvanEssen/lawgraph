"""A database that cannot be reached is one answer everywhere: a 503 with ``Retry-After``
(a page of ``/render`` without a body, so Caddy serves the shell); an unexpected error is a
500 with one line in the request log."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from lawgraph.api import dependencies
from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.api.routes import government
from lawgraph.db.schema import SchemaOutdated
from lawgraph.db.store import DatabaseUnavailable

_SECRET = "connection to db.internal:5432 failed"


def _unreachable() -> None:
    raise DatabaseUnavailable(_SECRET)


@pytest.mark.parametrize(
    "path",
    ["/api/health", "/api/judgments/ECLI:NL:HR:2020:1", "/render/wetten/BWBR0005289"],
)
def test_an_unreachable_database_is_a_503_with_retry_after(
    path: str, caplog: pytest.LogCaptureFixture
) -> None:
    app.dependency_overrides[get_store] = _unreachable
    with caplog.at_level("WARNING"):
        response = TestClient(app, raise_server_exceptions=False).get(path)

    assert response.status_code == 503
    assert response.headers["retry-after"] == "30"
    assert _SECRET not in response.text
    assert any(_SECRET in m for m in caplog.messages)


def test_a_page_of_render_is_an_empty_503() -> None:
    app.dependency_overrides[get_store] = _unreachable
    response = TestClient(app, raise_server_exceptions=False).get(
        "/render/wetten/BWBR0005289"
    )
    assert response.status_code == 503
    assert response.content == b""


class _DeadStore:
    def ping(self) -> None:
        raise DatabaseUnavailable(_SECRET)


def test_health_without_a_database_says_so_without_its_error() -> None:
    app.dependency_overrides[get_store] = _DeadStore
    response = TestClient(app, raise_server_exceptions=False).get("/api/health")
    assert response.status_code == 503
    assert response.json() == {
        "detail": "The database is unavailable. Try again later."
    }


class _BrokenStore:
    def ping(self) -> None:
        pass

    def pool_usage(self) -> dict:
        raise RuntimeError("a bug in the health check")


def test_a_bug_in_health_is_no_database_down() -> None:
    app.dependency_overrides[get_store] = _BrokenStore
    response = TestClient(app, raise_server_exceptions=False).get("/api/health")
    assert response.status_code == 500
    assert "a bug" not in response.text


def test_an_outdated_schema_is_a_503_that_says_so(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def outdated() -> None:
        raise SchemaOutdated(
            "schema outdated, build it again (articles.stub is missing)"
        )

    app.dependency_overrides[get_store] = outdated
    response = TestClient(app, raise_server_exceptions=False).get("/api/health")
    assert response.status_code == 503
    assert response.json() == {"detail": "The database schema is outdated."}


def test_an_unexpected_error_has_one_line_in_the_request_log(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def broken(store: object) -> None:
        raise RuntimeError("a bug")

    monkeypatch.setattr(government, "get_cabinets", broken)
    with caplog.at_level("INFO", logger="lawgraph.api.app"):
        response = TestClient(app, raise_server_exceptions=False).get("/api/cabinets")

    assert response.status_code == 500
    lines = [r for r in caplog.records if "→ 500" in r.getMessage()]
    assert len(lines) == 1
    assert "GET /api/cabinets" in lines[0].getMessage()
    assert lines[0].exc_info is not None


def test_a_refused_schema_is_remembered_not_tried_per_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built: list[int] = []

    def outdated() -> None:
        built.append(1)
        raise SchemaOutdated("schema outdated")

    monkeypatch.setattr(dependencies, "GraphStore", outdated)
    monkeypatch.setattr(dependencies, "_store", None)
    monkeypatch.setattr(dependencies, "_refused", None, raising=False)
    for _ in range(3):
        with pytest.raises(SchemaOutdated):
            dependencies.get_store()
    assert built == [1]


def test_an_unreachable_database_is_tried_again(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built: list[int] = []

    def unreachable() -> None:
        built.append(1)
        raise DatabaseUnavailable(_SECRET)

    monkeypatch.setattr(dependencies, "GraphStore", unreachable)
    monkeypatch.setattr(dependencies, "_store", None)
    for _ in range(2):
        with pytest.raises(DatabaseUnavailable):
            dependencies.get_store()
    assert built == [1, 1]

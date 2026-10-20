"""Every error the API answers on a real PostgreSQL, in one shape: JSON ``{"detail": "…"}``,
the detail a sentence. A 404 says what was not found (``"<What> '<key>' not found."``), a
422 names its parameter first (``"`param`: what is wrong."``), a 503 says what to do; an
unexpected error is a 500 with ``request_id`` beside its detail, the same id as its
``X-Request-ID`` header and its line in the log, and nothing of its cause."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.db import GraphStore
from lawgraph.db.queries.nodes import FULL_BUCKET_LIMIT, NEIGHBORHOOD_CAP
from tests.asserts import assert_status

NOT_FOUND = re.compile(r"^.+ '.+' not found\.$")
INVALID = re.compile(r"^`[^`]+`(, `[^`]+`)*: .+\.$")


@pytest.fixture()
def client(store: GraphStore) -> Iterator[TestClient]:
    store.bulk_insert_or_update_nodes(
        "factions",
        [
            {
                "key": "vvd",
                "type": "faction",
                "labels": [],
                "props": {"name": "VVD", "abbreviation": "VVD", "chamber": "TK"},
            }
        ],
    )
    app.dependency_overrides[get_store] = lambda: store
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.pop(get_store, None)


def _error(client: TestClient, url: str, status: int) -> str:
    """The detail of the error *url* answers, after checking its status and shape."""
    response = client.get(url)
    assert response.status_code == status, (url, response.text)
    assert response.headers["content-type"] == "application/json", url
    body: dict[str, Any] = response.json()
    assert list(body) == ["detail"], (url, body)
    assert isinstance(body["detail"], str), (url, body)
    return body["detail"]


@pytest.mark.parametrize(
    ("url", "detail"),
    [
        ("/api/nodes/instruments/NOPE", "Node 'NOPE' not found."),
        (
            "/api/instruments/BWBR9999999/articles?division=deel-hoofdstuk-1",
            "Division 'deel-hoofdstuk-1' not found.",
        ),
        (
            "/api/instruments/BWBR9999999/articles/at/2024-01-01"
            "?division=deel-hoofdstuk-1",
            "Division 'deel-hoofdstuk-1' not found.",
        ),
        ("/api/lookup?kind=dossier&number=99999", "Dossier '99999' not found."),
        (
            "/api/lookup?kind=document&dossier=99999&number=3",
            "Document '99999, 3' not found.",
        ),
        (
            "/api/parliament/seats?chamber=EK&date=1990-01-01",
            "Seats of the Eerste Kamer '1990-01-01' not found.",
        ),
        ("/api/no-such-route", "Route '/api/no-such-route' not found."),
    ],
)
def test_a_404_says_what_was_not_found(client: TestClient, url: str, detail: str):
    assert _error(client, url, 404) == detail
    assert NOT_FOUND.match(detail)


@pytest.mark.parametrize(
    ("url", "param"),
    [
        # FastAPI's own validation
        ("/api/feed?limit=abc", "limit"),
        ("/api/nodes/heat?months=abc", "months"),
        ("/api/search?q=x&from=gisteren", "from"),
        # the checks of the routes
        ("/api/search?q=x&types=nope", "types"),
        ("/api/search?q=x&from=2024-02-01&to=2024-01-01", "from"),
        ("/api/nodes/raw_sources/x", "collection"),
        ("/api/nodes/raw_sources/x/neighborhood", "collection"),
        ("/api/nodes/instruments/x?status=nope", "status"),
        ("/api/nodes/instruments/x?relations=NOPE", "relations"),
        (f"/api/nodes/instruments/x?limit={FULL_BUCKET_LIMIT + 1}", "limit"),
        (
            f"/api/nodes/instruments/x/neighborhood?depth=2&cap={NEIGHBORHOOD_CAP + 1}",
            "cap",
        ),
        pytest.param(
            "/api/nodes/heat?ids=" + ",".join(f"a/{i}" for i in range(501)),
            "ids",
            id="heat-ids",
        ),
        ("/api/paths?ids=instruments/a", "ids"),
        ("/api/paths?ids=a,b", "ids"),
        ("/api/decisions?vote=voor", "vote"),
        ("/api/lookup?kind=dossier", "number"),
        ("/api/lookup?kind=publication&series=xx&year=2020&number=1", "series"),
        ("/api/lookup?kind=publication&series=stb&year=20x0&number=1", "year"),
        ("/api/feed?" + "&".join(f"q=woord{i}" for i in range(11)), "q"),
        ("/api/feed?article=1", "article"),
        ("/api/feed?cursor=zzz", "cursor"),
        ("/api/feed/periods?member=x", "member"),
        ("/api/feed/periods?per=day", "since"),
        ("/api/factions/vvd/votes", "key"),
    ],
)
def test_a_422_names_its_parameter_first(client: TestClient, url: str, param: str):
    detail = _error(client, url, 422)
    assert INVALID.match(detail), (url, detail)
    assert f"`{param}`" in detail.split(":", 1)[0], (url, detail)


def test_lookup_names_every_missing_parameter(client: TestClient):
    assert (
        _error(client, "/api/lookup?kind=document", 422)
        == "`dossier`, `number`: missing."
    )


def test_an_unknown_choice_lists_what_is_allowed(client: TestClient):
    detail = _error(client, "/api/search?q=x&types=nope", 422)
    assert detail.startswith("`types`: unknown nope. Allowed: "), detail


def test_the_heat_not_counted_yet_is_a_503_without_the_pipeline(client: TestClient):
    detail = _error(client, "/api/nodes/heat", 503)
    assert detail == "The heat of the whole graph is not counted yet. Try again later."


def test_an_unexpected_error_is_a_json_500_with_its_request_id(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
):
    def broken(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("SELECT secret FROM lg_nodes")

    monkeypatch.setattr("lawgraph.api.routes.nodes.get_node_with_neighbors", broken)
    with caplog.at_level(logging.ERROR, logger="lawgraph.api.middleware"):
        response = client.get("/api/nodes/instruments/x")
    assert_status(response, 500)
    assert response.headers["content-type"] == "application/json"
    body = response.json()
    request_id = response.headers["X-Request-ID"]
    assert body == {"detail": "Internal error.", "request_id": request_id}
    assert "secret" not in response.text
    (record,) = [r for r in caplog.records if request_id[:8] in r.getMessage()]
    assert record.exc_info is not None and "secret" in str(record.exc_info[1])

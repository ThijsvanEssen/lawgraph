"""After a migration the front end sees the new data within a minute: a response may be used
for 60 seconds, and carries an ``ETag`` of the data version, which a write to the graph
changes. Asking again with ``If-None-Match`` costs a 304 while nothing changed."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import COLLECTION_JUDGMENTS
from lawgraph.db import GraphStore, version_cache
from tests.asserts import assert_status

PATH = "/api/judgments/ECLI:NL:HR:2020:1"


def _put(store: GraphStore, summary: str) -> None:
    store.bulk_insert_or_update_nodes(
        COLLECTION_JUDGMENTS,
        [
            {
                "key": "ecli_nl_hr_2020_1",
                "type": "judgment",
                "labels": [],
                "props": {"ecli": "ECLI:NL:HR:2020:1", "summary": summary},
            }
        ],
    )


def test_a_write_to_the_graph_changes_the_etag(store: GraphStore) -> None:
    """The tag follows the data version as ``version_cache`` reads it (``VERSION_TTL``,
    nought in the tests)."""
    _put(store, "Oude samenvatting.")
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        first = client.get(PATH)
        unchanged = client.get(PATH, headers={"If-None-Match": first.headers["etag"]})
        _put(store, "Nieuwe samenvatting.")
        changed = client.get(PATH, headers={"If-None-Match": first.headers["etag"]})
    finally:
        app.dependency_overrides.pop(get_store, None)

    assert_status(first, 200)
    assert first.headers["cache-control"] == "public, max-age=60"
    assert first.headers["etag"].startswith('W/"')
    assert_status(unchanged, 304)
    assert_status(changed, 200)
    assert changed.headers["etag"] != first.headers["etag"]
    body: dict[str, Any] = changed.json()
    assert body["judgment"]["props"]["summary"] == "Nieuwe samenvatting."


def test_a_large_answer_is_compressed_and_still_validated(store: GraphStore) -> None:
    _put(store, "Een samenvatting. " * 200)
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        gzip = {"Accept-Encoding": "gzip"}
        first = client.get(PATH, headers=gzip)
        again = client.get(
            PATH, headers={**gzip, "If-None-Match": first.headers["etag"]}
        )
        plain = client.get(PATH, headers={"Accept-Encoding": "identity"})
        atom = client.get("/api/feed.atom", headers=gzip)
    finally:
        app.dependency_overrides.pop(get_store, None)

    assert_status(first, 200)
    assert first.headers["content-encoding"] == "gzip"
    assert "Accept-Encoding" in first.headers["vary"]
    assert first.headers["etag"].startswith('W/"')
    assert first.json()["judgment"]["props"]["summary"].startswith("Een samenvatting.")
    assert_status(again, 304)
    assert "content-encoding" not in plain.headers
    assert plain.headers["etag"] == first.headers["etag"]
    # the Atom feed of an empty graph is small; its headers say what a large one gets
    assert_status(atom, 200)
    assert atom.headers["etag"] == first.headers["etag"]
    # a feed reader polls: any cache may keep it a quarter of an hour
    assert atom.headers["cache-control"] == "public, max-age=900"


def test_a_release_changes_the_etag_and_every_answer_says_how_to_keep_it(
    store: GraphStore,
) -> None:
    """A browser that kept an answer of an older release asks with its tag and gets the
    new answer, not a 304: the tag holds the API version. An error is never kept."""
    _put(store, "Een samenvatting.")
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        first = client.get(PATH)
        data_version = first.headers["etag"].rsplit("-", 1)[1].rstrip('"')
        older_release = client.get(
            PATH, headers={"If-None-Match": f'W/"0.0.1-{data_version}"'}
        )
        missing = client.get("/api/judgments/ECLI:NL:HR:1999:1")
        invalid = client.get("/api/feed?kind=roddel")
    finally:
        app.dependency_overrides.pop(get_store, None)

    assert first.headers["etag"].startswith(f'W/"{app.version}-')
    assert_status(older_release, 200)
    assert (missing.status_code, missing.headers["cache-control"]) == (
        404,
        "no-store",
    ), missing.text
    assert (invalid.status_code, invalid.headers["cache-control"]) == (
        422,
        "no-store",
    ), invalid.text
    assert "etag" not in missing.headers


def test_the_data_version_is_read_once_per_ttl(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The tag, the routes and the health read one data version (``current_version``): at
    most one read of it per ``VERSION_TTL`` per process, whatever is asked."""
    _put(store, "Een samenvatting.")
    monkeypatch.setattr(version_cache, "VERSION_TTL", 60.0)
    reads = 0
    table_versions = store.table_versions

    def counted() -> dict[str, int]:
        nonlocal reads
        reads += 1
        return table_versions()

    monkeypatch.setattr(store, "table_versions", counted)
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        tags = {client.get(PATH).headers["etag"] for _ in range(3)}
        client.get("/api/health")
    finally:
        app.dependency_overrides.pop(get_store, None)

    assert len(tags) == 1
    assert reads == 1

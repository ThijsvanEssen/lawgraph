"""After a migration the front end sees the new data within a minute: a response may be used
for 60 seconds, and carries an ``ETag`` of the data version, which a write to the graph
changes. Asking again with ``If-None-Match`` costs a 304 while nothing changed."""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api import app as app_module
from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import COLLECTION_JUDGMENTS
from lawgraph.db import ArangoStore

PATH = "/api/judgments/ECLI:NL:HR:2020:1"


def _put(store: ArangoStore, summary: str) -> None:
    store.bulk_insert_or_update_nodes(
        COLLECTION_JUDGMENTS,
        [
            {
                "_key": "ecli_nl_hr_2020_1",
                "type": "judgment",
                "labels": [],
                "props": {"ecli": "ECLI:NL:HR:2020:1", "summary": summary},
            }
        ],
    )


def test_a_write_to_the_graph_changes_the_etag(
    database: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(app_module, "DATA_VERSION_TTL", 0.0)  # read it on every request
    store = ArangoStore()
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

    assert first.status_code == 200
    assert first.headers["cache-control"] == "public, max-age=60"
    assert first.headers["etag"].startswith('W/"')
    assert unchanged.status_code == 304
    assert changed.status_code == 200
    assert changed.headers["etag"] != first.headers["etag"]
    body: dict[str, Any] = changed.json()
    assert body["judgment"]["props"]["summary"] == "Nieuwe samenvatting."

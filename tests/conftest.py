from __future__ import annotations

import importlib
import os
from collections.abc import Iterator
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from lawgraph.core.models import Node

# The suite is offline unless asked otherwise; a developer's .env must not switch that on.
os.environ.setdefault("ALLOW_NETWORK_TESTS", "0")
# Every TestClient request comes from one address, and a suite asks the API far more than
# the 200 a minute a visitor may: the limit itself is tested on an instance of its own.
os.environ["LAWGRAPH_RATE_LIMIT_CALLS"] = "1000000"
# The API warms its answers up in the background at its start; the tests ask themselves.
os.environ["LAWGRAPH_API_WARM_UP"] = "false"


@pytest.fixture(autouse=True)
def _fresh_version_cache(monkeypatch) -> Iterator[None]:
    """Every test reads the data version at every call and starts with nothing kept: a test
    writes and reads again within the seconds the API keeps an answer."""
    from lawgraph.db import version_cache

    monkeypatch.setattr(version_cache, "VERSION_TTL", 0.0)
    version_cache.clear()
    yield
    version_cache.clear()


@pytest.fixture(autouse=True)
def _own_pacer_locks(tmp_path_factory: pytest.TempPathFactory, monkeypatch) -> None:
    """The host locks of the pacer in a directory of the test run, not the machine's.

    A ``lawgraph retrieve`` running next to the suite holds the real locks, and the tests
    would find every host "taken" and paced at half speed.
    """
    from lawgraph.clients import pacing

    lock_dir = tmp_path_factory.getbasetemp() / "pacer-locks"
    lock_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(pacing, "_lock_dir", lambda: lock_dir)


@pytest.fixture()
def patch_route_stores(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub get_store in route modules to prevent opening a real GraphStore."""
    store_stub = object()
    for module_name in (
        "lawgraph.api.routes.articles",
        "lawgraph.api.routes.judgments",
        "lawgraph.api.routes.nodes",
    ):
        module = importlib.import_module(module_name)
        monkeypatch.setattr(module, "get_store", lambda store=store_stub: store)


def remove_edges_from(edges: dict[str, dict], bind: dict) -> Iterator[int]:
    """What ``semantic_queries.remove_edges_from`` does, on *edges* (key -> edge); with
    ``relations`` bound, what ``remove_edges_to`` does."""
    end, relations = (
        ("_to", bind["relations"])
        if "relations" in bind
        else ("_from", [bind["relation"]])
    )
    gone = [
        key
        for key, edge in edges.items()
        if edge[end] in bind["ids"]
        and edge.get("relation") in relations
        and edge.get("source") == bind["source"]
        and key not in bind["keep"].get(edge[end], [])
    ]
    for key in gone:
        del edges[key]
    return iter([1] * len(gone))


class _BaseFakeStore:
    """In-memory upserts that report created versus updated like ``GraphStore``."""

    def __init__(self) -> None:
        self.edges: dict[str, dict] = {}
        self.nodes: dict[str, dict[str, dict]] = {}

    def bulk_insert_or_update_nodes(
        self, collection: str, docs: list[dict]
    ) -> tuple[int, int]:
        bucket = self.nodes.setdefault(collection, {})
        created = 0
        for doc in docs:
            if doc["_key"] not in bucket:
                created += 1
            bucket[doc["_key"]] = doc
        return created, len(docs) - created

    def insert_or_update(self, node: Node) -> tuple[Node, bool]:
        created, _ = self.bulk_insert_or_update_nodes(
            node.collection, [node.to_document()]
        )
        return node, created == 1

    def bulk_insert_or_update_edges(self, docs: list[dict]) -> tuple[int, int]:
        created = 0
        for doc in docs:
            key = doc.get("_key", "")
            is_new = key not in self.edges
            self.edges[key] = doc
            if is_new:
                created += 1
        return created, len(docs) - created

    def insert_or_update_edge(self, doc: dict) -> tuple[dict, bool]:
        key = doc.get("_key", "")
        is_new = key not in self.edges
        self.edges[key] = doc
        return doc, is_new

    def remove_edges_from(self, bind: dict) -> Iterator[int]:
        return remove_edges_from(self.edges, bind)

    def get_node(self, collection: str, key: str) -> dict | None:
        raise NotImplementedError

    def existing_keys(self, collection: str, keys) -> set[str]:
        """On top of the ``get_node`` of the subclass."""
        return {k for k in set(keys) if self.get_node(collection, k) is not None}

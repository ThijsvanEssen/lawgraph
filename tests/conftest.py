from __future__ import annotations

import importlib
import os
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from lawgraph.core.models import Node

# The suite is offline unless asked otherwise; a developer's .env must not switch that on.
os.environ.setdefault("ALLOW_NETWORK_TESTS", "0")


@pytest.fixture()
def patch_route_stores(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stub get_store in route modules to prevent opening a real ArangoStore."""
    store_stub = object()
    for module_name in (
        "lawgraph.api.routes.articles",
        "lawgraph.api.routes.judgments",
        "lawgraph.api.routes.nodes",
    ):
        module = importlib.import_module(module_name)
        monkeypatch.setattr(module, "get_store", lambda store=store_stub: store)


class _BaseFakeStore:
    """In-memory upserts that report created versus updated like ``ArangoStore``."""

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

    def get_node(self, collection: str, key: str) -> dict | None:
        raise NotImplementedError

    def existing_keys(self, collection: str, keys) -> set[str]:
        """On top of the ``get_node`` of the subclass."""
        return {k for k in set(keys) if self.get_node(collection, k) is not None}

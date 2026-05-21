from __future__ import annotations

import importlib

import pytest


@pytest.fixture()
def stub_store(monkeypatch: pytest.MonkeyPatch) -> None:
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
    def __init__(self) -> None:
        self.edges: dict[str, dict] = {}

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
        return None

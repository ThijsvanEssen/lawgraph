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

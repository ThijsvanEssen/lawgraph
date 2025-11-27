from __future__ import annotations

import importlib

import pytest


@pytest.fixture(autouse=True)
def stub_store(monkeypatch: pytest.MonkeyPatch) -> None:
    """Voorkom dat tests de echte ArangoStore openen door een stub te gebruiken."""
    store_stub = object()
    for module_name in (
        "lawgraph.api.routes.articles",
        "lawgraph.api.routes.judgments",
        "lawgraph.api.routes.nodes",
    ):
        module = importlib.import_module(module_name)
        monkeypatch.setattr(module, "get_store", lambda store=store_stub: store)

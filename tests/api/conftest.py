from __future__ import annotations

from collections.abc import Generator

import pytest

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from tests.api.stubs import LOADERS, MockStore, route_modules


@pytest.fixture(autouse=True)
def stub_store_override() -> Generator[None]:
    app.dependency_overrides[get_store] = MockStore
    yield
    app.dependency_overrides.pop(get_store, None)


@pytest.fixture(autouse=True)
def stub_article_relationship_data(monkeypatch) -> None:
    """Default the article-detail relationship enrichment to empty.

    Tests exercising the relationships view override this with their own
    monkeypatch.setattr after the fixture has run.
    """
    monkeypatch.setattr(
        "lawgraph.api.routes.articles.get_article_relationship_data",
        lambda store, article_id: {"upstream": [], "downstream": [], "scope": []},
    )


@pytest.fixture(autouse=True)
def stub_loaders(monkeypatch) -> None:
    """The routes read the loaders' stand-ins (``LOADERS``), not a database."""
    for module in route_modules():
        for name, stand_in in LOADERS.items():
            if hasattr(module, name):
                monkeypatch.setattr(module, name, stand_in)


@pytest.fixture(autouse=True)
def stub_unlinked_count(monkeypatch) -> None:
    """No step read the references of a record (``unlinked_count``): its
    ``completeness`` is null unless a test stubs a count."""
    for module in route_modules():
        if hasattr(module, "unlinked_count"):
            monkeypatch.setattr(module, "unlinked_count", lambda store, node: None)

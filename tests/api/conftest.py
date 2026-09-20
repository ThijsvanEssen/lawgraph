from __future__ import annotations

from collections.abc import Generator

import pytest

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store


@pytest.fixture(autouse=True)
def stub_store_override() -> Generator[None, None, None]:
    app.dependency_overrides[get_store] = lambda: None
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

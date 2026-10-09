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


# The names of the dossiers the routes put next to a bare number, as ``load_dossier_names``
# reads them: one budget chapter and one bill.
DOSSIER_NAMES = {
    "36000": {
        "number": "36000",
        "short_title": "Wet beter voorbeeld",
        "title": "Wijziging van de Wet X (Wet beter voorbeeld)",
    },
}


@pytest.fixture(autouse=True)
def stub_dossier_names(monkeypatch) -> None:
    """The routes read ``DOSSIER_NAMES``, not a database."""
    for module in ("committees", "decisions", "documents", "nodes"):
        monkeypatch.setattr(
            f"lawgraph.api.routes.{module}.load_dossier_names",
            lambda store: DOSSIER_NAMES,
        )


# The slugs of the members the routes put a member's readable address by: one.
MEMBER_SLUGS = {"m_bakker": "bram-bakker"}


@pytest.fixture(autouse=True)
def stub_member_slugs(monkeypatch) -> None:
    """The routes read ``MEMBER_SLUGS``, not a database."""
    for module in ("decisions", "documents", "government", "feed"):
        monkeypatch.setattr(
            f"lawgraph.api.routes.{module}.load_member_slugs",
            lambda store: MEMBER_SLUGS,
        )

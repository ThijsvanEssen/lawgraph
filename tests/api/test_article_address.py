"""Every article route reads the article by one address: ``6:162`` (as cited) and ``162``
(its own number) under BW Boek 6 are the same article, on each subroute."""

from __future__ import annotations

from collections.abc import Generator
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.db.queries.articles import ArticleDetailData
from tests.asserts import assert_status
from tests.fakes import FakeStoreBase

client = TestClient(app)

BW6 = "BWBR0005289"
ARTICLE = {
    "id": "articles/bwbr0005289_162",
    "key": "bwbr0005289_162",
    "props": {"bwb_id": BW6, "article_number": "162", "display_name": "Artikel 162"},
    "labels": ["Article"],
}


class _Store(FakeStoreBase):
    """Knows the one article."""

    def get_document(self, collection: str, key: str) -> dict[str, Any] | None:
        return ARTICLE if (collection, key) == ("articles", ARTICLE["key"]) else None

    def has_node(self, collection: str, key: str) -> bool:
        return self.get_document(collection, key) is not None


@pytest.fixture
def calls(monkeypatch) -> Generator[list[tuple[str, tuple[Any, ...]]]]:
    """The queries the routes call, with the arguments after the store."""
    seen: list[tuple[str, tuple[Any, ...]]] = []

    def stub(name: str, answer: Any) -> None:
        def query(store: Any, *args: Any, **kwargs: Any) -> Any:
            seen.append((name, args + tuple(sorted(kwargs.items()))))
            return answer

        monkeypatch.setattr(f"lawgraph.api.routes.articles.{name}", query)

    stub(
        "get_article_with_relations",
        ArticleDetailData(article=ARTICLE, instrument=None, metadata={}),
    )
    stub("get_article_citations", [])
    stub("article_terms", ([], {}, []))
    stub("get_article_relationship_data", {})
    stub(
        "get_article_cited_by",
        SimpleNamespace(rows=[], total=0, judgment_total=0, echr_judgment_total=0),
    )
    stub(
        "get_article_history",
        SimpleNamespace(article=ARTICLE, versions=[], dossier_titles={}),
    )
    stub(
        "get_article_version",
        SimpleNamespace(
            article=ARTICLE, versions=[{"key": "v1", "props": {}}], dossier_titles={}
        ),
    )
    stub("get_article_legislative_history", [])
    stub("get_article_explanations", {"total": 0, "items": []})
    stub("get_article_explanation_passages", [])
    stub("load_dossier_names", {})
    stub("get_delegated_regulations", [])
    app.dependency_overrides[get_store] = _Store
    yield seen
    app.dependency_overrides.pop(get_store, None)


SUBROUTES = (
    "",
    "/cited-by",
    "/history",
    "/history/v1",
    "/legislative-history",
    "/explained-by",
    "/explanations",
    "/delegated",
)


@pytest.mark.parametrize("subroute", SUBROUTES)
def test_both_numberings_read_the_same_article(calls, subroute: str) -> None:
    answers = []
    for number in ("6:162", "162"):
        calls.clear()
        response = client.get(f"/api/articles/{BW6}/{number}{subroute}")
        assert response.status_code == 200, response.text
        answers.append((response.json(), list(calls)))
    assert answers[0] == answers[1]
    body, queries = answers[1]
    assert queries and all("6:162" not in repr(args) for _, args in queries)
    if "article_id" in body:
        assert body["article_id"] == ARTICLE["id"]


@pytest.mark.parametrize("subroute", ("/cited-by", "/delegated"))
def test_an_unknown_article_is_a_404(calls, subroute: str) -> None:
    response = client.get(f"/api/articles/{BW6}/999{subroute}")
    assert_status(response, 404)

from __future__ import annotations

from typing import Any

import psycopg
import pytest

from lawgraph.db.queries import warm_nodes


def _articles(*keys: str) -> list[dict[str, Any]]:
    return [{"key": k, "id": f"articles/{k}"} for k in keys]


def test_warms_the_node_and_first_citing_pages_of_each_article_most_cited_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked: list[tuple[str, str, Any]] = []
    monkeypatch.setattr(
        warm_nodes, "most_cited_articles", lambda store, n: _articles("a", "b")
    )
    monkeypatch.setattr(
        warm_nodes,
        "get_node_with_neighbors",
        lambda store, collection, key: asked.append(("node", key, None)),
    )
    monkeypatch.setattr(
        warm_nodes,
        "get_article_cited_by",
        lambda store, id_, sort, limit: asked.append(("cited", id_, (sort, limit))),
    )
    warm_nodes.warm_articles(None)  # type: ignore[arg-type]
    pages = len(warm_nodes.FIRST_PAGES["article_citations"])
    assert [a[:2] for a in asked if a[0] == "node"] == [("node", "a"), ("node", "b")]
    assert len([a for a in asked if a[0] == "cited"]) == 2 * pages


def test_past_its_time_it_stops_at_once(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[str] = []
    monkeypatch.setattr(
        warm_nodes, "most_cited_articles", lambda store, n: _articles("a")
    )
    monkeypatch.setattr(
        warm_nodes, "get_node_with_neighbors", lambda *a: asked.append("node")
    )
    warm_nodes.warm_articles(None, seconds=0.0)  # type: ignore[arg-type]
    assert asked == []


def test_a_database_error_costs_only_the_warmth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(store: object, n: int) -> list[dict[str, Any]]:
        raise psycopg.OperationalError("down")

    monkeypatch.setattr(warm_nodes, "most_cited_articles", fail)
    warm_nodes.warm_most_cited_nodes(None)  # type: ignore[arg-type]

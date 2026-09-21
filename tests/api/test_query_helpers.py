"""Query helpers extracted from routes: one bulk query per call, none when empty."""

from __future__ import annotations

from lawgraph.api.queries.articles import get_articles_by_keys
from lawgraph.api.queries.documents import list_documents
from lawgraph.api.queries.instruments import get_short_titles


class _CountingStore:
    def __init__(self, rows: list[dict] | None = None) -> None:
        self.rows = rows or []
        self.calls: list[tuple[str, dict]] = []

    def query(self, aql: str, bind_vars: dict | None = None):
        self.calls.append((aql, bind_vars or {}))
        return self.rows


def test_articles_by_keys_is_one_query_and_deduplicates() -> None:
    store = _CountingStore([{"_key": "a", "_id": "articles/a"}])

    result = get_articles_by_keys(store, ["a", "a", "b"])

    assert list(result) == ["a"]
    assert len(store.calls) == 1
    assert sorted(store.calls[0][1]["keys"]) == ["a", "b"]


def test_articles_by_keys_empty_does_not_query() -> None:
    store = _CountingStore()
    assert get_articles_by_keys(store, []) == {}
    assert store.calls == []


def test_short_titles_prefers_short_title_and_falls_back() -> None:
    store = _CountingStore(
        [
            {"bwb_id": "BWBR1", "short_title": "Sr", "citation_title": "Wetboek"},
            {"bwb_id": "BWBR2", "short_title": None, "citation_title": "Wegenwet"},
            {"celex": "32016R0679", "short_title": "AVG"},
            {"bwb_id": "BWBR3"},  # no title at all -> skipped
        ]
    )

    by_bwb, by_celex = get_short_titles(store, {"BWBR1", "BWBR2", "BWBR3"}, {"x"})

    assert by_bwb == {"BWBR1": "Sr", "BWBR2": "Wegenwet"}
    assert by_celex == {"32016R0679": "AVG"}
    assert len(store.calls) == 1


def test_short_titles_empty_does_not_query() -> None:
    store = _CountingStore()
    assert get_short_titles(store, set(), set()) == ({}, {})
    assert store.calls == []


def test_list_documents_builds_filters_into_one_query() -> None:
    store = _CountingStore([{"key": "k"}])

    rows = list_documents(
        store, q="wet", kind="Brief", chamber="tk", source=None, limit=10
    )

    assert rows == [{"key": "k"}]
    ((aql, bind),) = store.calls
    assert "FILTER @chamber IN document.labels" in aql
    assert bind["chamber"] == "TK" and bind["limit"] == 10
    assert "@source" not in aql

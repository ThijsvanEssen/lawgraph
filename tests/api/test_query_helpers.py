"""Query helpers extracted from routes: one bulk query per call, none when empty."""

from __future__ import annotations

from lawgraph.api.queries.documents import list_documents
from lawgraph.api.queries.instruments import get_short_titles


class _CountingStore:
    def __init__(self, rows: list[dict] | None = None) -> None:
        self.rows = rows or []
        self.calls: list[tuple[str, dict]] = []

    def query(self, aql: str, bind_vars: dict | None = None):
        self.calls.append((aql, bind_vars or {}))
        return self.rows


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
    store = _CountingStore([{"total": 7, "items": [{"key": "k"}]}])

    page = list_documents(
        store,
        q="wet",
        kind="Brief",
        chamber="tk",
        source=None,
        dossier_id=None,
        limit=10,
        offset=20,
    )

    assert page == {"total": 7, "items": [{"key": "k"}]}
    ((aql, bind),) = store.calls
    assert aql.count("FILTER @chamber IN document.labels") == 2  # count and page
    assert bind["chamber"] == "TK" and bind["limit"] == 10 and bind["offset"] == 20
    assert "@source" not in aql and "@dossier_id" not in aql


def test_list_documents_of_a_dossier_reads_that_dossiers_documents() -> None:
    store = _CountingStore()

    page = list_documents(
        store,
        q=None,
        kind=None,
        chamber=None,
        source=None,
        dossier_id="dossiers/36000",
        limit=10,
        offset=0,
    )

    assert page == {"total": 0, "items": []}
    ((aql, bind),) = store.calls
    assert "FOR document IN all_documents" in aql
    assert bind["dossier_id"] == "dossiers/36000" and "part_of" in bind

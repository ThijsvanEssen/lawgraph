"""Lists paged by ``after`` (``db/queries/_keyset.py``) on a real PostgreSQL: the pages
follow one another in the order of the list with no row twice and none missing, for every
order, rows with nothing in a sort key and several with the same value in it among them; a
deep page is read by the index in the order of the list, not by skipping rows."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.db import GraphStore
from lawgraph.db.queries._keyset import InvalidCursor
from lawgraph.db.queries.documents import DOCUMENT_ORDER, list_documents
from lawgraph.db.queries.instruments import get_instruments_list
from tests.pg.plans import explain, plan_nodes


def _doc(
    key: str, node_type: str, labels: list[str] | None = None, **props: Any
) -> dict[str, Any]:
    return {"key": key, "type": node_type, "labels": labels or [], "props": props}


def _seed(store: GraphStore) -> None:
    titles = ["Wet a", "Wet b", "Wet b", None, "Wet c", None, "Wet a", "Wet d", "Wet e"]
    counts = [3, None, 3, 1, None, 7, 7, 3, 0]
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            _doc(
                f"i{n:02d}",
                "instrument",
                bwb_id=f"BWBR{n:04d}",
                kind="wet",
                jurisdiction="nl",
                title=f"T{n}",
                citation_title=title,
                article_count=count,
            )
            for n, (title, count) in enumerate(zip(titles, counts, strict=True))
        ],
    )
    days = ["2025-03-01", "2025-03-01", "2025-02-01", "2025-03-01", "2025-01-01"] * 2
    store.bulk_insert_or_update_nodes(
        "documents",
        [
            _doc(f"d{n:02d}", "document", ["TK"], kind="Motie", date=day)
            for n, day in enumerate(days)
        ],
    )


def _walk(read: Any, size: int) -> list[str]:
    """The keys of every page, following ``next_cursor`` until the last."""
    keys: list[str] = []
    after = None
    for _ in range(50):
        page = read(size, after)
        keys += [item["key"] for item in page["items"]]
        after = page["next_cursor"]
        if after is None:
            return keys
    raise AssertionError("never ends")


@pytest.mark.parametrize("size", [1, 2, 4, 100])
@pytest.mark.parametrize("sort", ["title", "article_count"])
def test_instruments_by_cursor_are_the_list_by_offset(
    store: GraphStore, sort: str, size: int
) -> None:
    _seed(store)

    def read(limit: int, after: str | None) -> dict[str, Any]:
        return get_instruments_list(
            store, sort=sort, limit=limit, after=after, facets=False
        )

    whole = get_instruments_list(store, sort=sort, limit=100, facets=False)["items"]
    assert len(whole) == 9
    assert _walk(read, size) == [item["key"] for item in whole]


@pytest.mark.parametrize("size", [1, 3, 100])
def test_documents_by_cursor_are_the_list_by_offset(
    store: GraphStore, size: int
) -> None:
    _seed(store)

    def read(limit: int, after: str | None) -> dict[str, Any]:
        return list_documents(store, limit=limit, after=after, facets=False)

    whole = list_documents(store, limit=100, facets=False)["items"]
    assert len(whole) == 10
    assert _walk(read, size) == [item["key"] for item in whole]


def test_a_page_by_offset_has_the_cursor_of_the_next(store: GraphStore) -> None:
    _seed(store)
    second = list_documents(store, limit=3, offset=3, facets=False)
    third = list_documents(store, limit=3, after=second["next_cursor"], facets=False)
    by_offset = list_documents(store, limit=3, offset=6, facets=False)
    assert [d["key"] for d in third["items"]] == [d["key"] for d in by_offset["items"]]


def test_a_cursor_of_another_list_is_refused(store: GraphStore) -> None:
    _seed(store)
    token = get_instruments_list(store, limit=1, facets=False)["next_cursor"]
    with pytest.raises(InvalidCursor):
        get_instruments_list(store, sort="article_count", after=token)
    with pytest.raises(InvalidCursor):
        list_documents(store, after=token)
    with pytest.raises(InvalidCursor):
        list_documents(store, after="not a token")


def test_a_deep_page_is_read_by_the_index_of_the_order(store: GraphStore) -> None:
    """The place after the cursor is a range of the index of the date, not a filter on
    rows read from the first."""
    _seed(store)
    token = list_documents(store, limit=2, facets=False)["next_cursor"]
    bind: dict[str, Any] = {}
    condition = DOCUMENT_ORDER.after(DOCUMENT_ORDER.values(token), bind)
    plan = explain(
        store,
        f"SELECT d.id FROM documents d WHERE d.date >= '0' AND ({condition}) "
        f"ORDER BY {DOCUMENT_ORDER.order} LIMIT 2",
        bind,
        disable=("seqscan", "bitmapscan"),
    )
    kinds = [node["Node Type"] for node in plan_nodes(plan)]
    assert "Sort" not in kinds, kinds
    assert any("Index" in kind for kind in kinds), kinds

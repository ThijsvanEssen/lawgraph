"""The articles of the narrow form of an article (``GET /api/articles/.../text`` and
``/batch``): each with its law, the end of its newest version, its successors, its
citations and the articles before and after it, for many articles in a few queries."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, cast

from lawgraph.core.reference_targets import reference_targets
from lawgraph.db import GraphStore
from lawgraph.db._rows import node_doc
from lawgraph.db.queries._helpers import run_together
from lawgraph.db.queries.articles import (
    ArticleCitationEntry,
    get_citations_of,
    present_targets,
)
from lawgraph.db.queries.instrument_scope import LawColumn, law_column, listed_article
from lawgraph.db.queries.relationships import (
    INSTRUMENT_COLUMNS,
    INSTRUMENT_FOR,
    article_successors,
    instrument_of_row,
)
from lawgraph.db.queries.validity import article_end_sql


@dataclass
class ArticleTextData:
    """An article with what its narrow form reads besides its props."""

    article: dict[str, Any]
    instrument: dict[str, Any] | None
    ended: str | None  # the ``valid_until`` of its newest version
    successors: list[dict[str, Any]] = field(default_factory=list)
    citations: list[ArticleCitationEntry] = field(default_factory=list)
    previous: dict[str, Any] | None = None
    next: dict[str, Any] | None = None


_ARTICLES = f"""
SELECT t.id, t.key, t.type, t.labels, t.props, {article_end_sql("t")} AS ended,
       {INSTRUMENT_COLUMNS}
FROM articles t
{INSTRUMENT_FOR}
WHERE t.key = ANY(%(keys)s)
"""

# The article before (``<``, newest first) or after (``>``) each of ``ids`` in the list of
# the articles of its law (``listed_article``, in the order of the document); none for an
# article without a place in it.
_NEIGHBOR = """
SELECT a.id AS of_id, n.id, n.key, n.type, n.labels,
       json_build_object('bwb_id', n.bwb_id, 'celex', n.celex,
                         'official_id', n.official_id,
                         'article_number', n.article_number,
                         'label', n.props -> 'label') AS props
FROM articles a
CROSS JOIN LATERAL (
    SELECT p.id, p.key, p.type, p.labels, p.bwb_id, p.celex, p.official_id,
           p.article_number, p.props
    FROM articles p
    WHERE p.{column} = a.{column} AND {listed} AND p.position IS NOT NULL
      AND (p.position, p.key) {side} (a.position, a.key)
    ORDER BY p.position {order} NULLS LAST, p.key {order} NULLS LAST
    LIMIT 1
) n
WHERE a.id = ANY(%(ids)s) AND a.position IS NOT NULL
"""


def _neighbors(
    store: GraphStore, column: LawColumn, ids: list[str], side: str
) -> dict[str, dict[str, Any]]:
    """The article on *side* (``<`` before, ``>`` after) of each of *ids*, whose law
    *column* names."""
    sql = _NEIGHBOR.format(
        column=column,
        listed=" AND ".join(listed_article("p")),
        side=side,
        order="DESC" if side == "<" else "ASC",
    )
    return {row["of_id"]: node_doc(row) for row in store.query(sql, {"ids": ids})}


def _around(
    store: GraphStore, docs: list[dict[str, Any]]
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    """The articles before and after each of *docs*, by its id: per column that names
    the laws of *docs*, one query a side."""
    by_column: dict[LawColumn, list[str]] = {}
    for doc in docs:
        by_column.setdefault(law_column(doc.get("props") or {}), []).append(doc["id"])
    before: dict[str, dict[str, Any]] = {}
    after: dict[str, dict[str, Any]] = {}
    for column, ids in by_column.items():
        before.update(_neighbors(store, column, ids, "<"))
        after.update(_neighbors(store, column, ids, ">"))
    return before, after


def get_article_texts(
    store: GraphStore, keys: list[str]
) -> tuple[dict[str, ArticleTextData], set[tuple[str, str]]]:
    """The articles of *keys* the data holds, by key, and the ``(collection, key)`` of the
    targets of their references the data holds (``present_targets``)."""
    rows = list(store.query(_ARTICLES, {"keys": list(keys)})) if keys else []
    if not rows:
        return {}, set()
    docs = [node_doc(row) for row in rows]
    ids = [doc["id"] for doc in docs]
    wanted: dict[str, set[str]] = {}
    for doc in docs:
        named = reference_targets((doc.get("props") or {}).get("references"))
        for collection, targets in named.items():
            wanted.setdefault(collection, set()).update(targets)
    found = run_together(
        lambda: article_successors(store, ids),
        lambda: get_citations_of(store, ids),
        lambda: present_targets(store, wanted),
        lambda: _around(store, docs),
    )
    successors = cast("dict[str, list[dict[str, Any]]]", found[0])
    citations = cast("dict[str, list[ArticleCitationEntry]]", found[1])
    present = cast("set[tuple[str, str]]", found[2])
    before, after = cast(
        "tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]", found[3]
    )
    texts = {
        doc["key"]: ArticleTextData(
            article=doc,
            instrument=instrument_of_row(row),
            ended=str(row["ended"]) if row["ended"] else None,
            successors=successors.get(doc["id"], []),
            citations=citations.get(doc["id"], []),
            previous=before.get(doc["id"]),
            next=after.get(doc["id"]),
        )
        for doc, row in zip(docs, rows, strict=True)
    }
    return texts, present

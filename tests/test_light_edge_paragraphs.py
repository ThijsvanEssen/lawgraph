"""The paragraphs a judgment cites in, on the edge of a neighbour (``_rows.light_edge_doc``):
taken from the mentions of an edge to an article, which a neighbour does not carry, and kept
as they are on an edge to a judgment."""

from __future__ import annotations

from lawgraph.db._rows import light_edge_doc, mentioned_paragraphs


def _row(meta: dict) -> dict:
    return {
        "key": "e1",
        "from_id": "judgments/a",
        "to_id": "articles/b",
        "doc": {"meta": meta},
    }


def test_the_mentions_give_their_paragraphs_in_order_each_once() -> None:
    mentions = [
        {"paragraph_id": "p1", "paragraph_number": "3.2", "snippet": "…"},
        {"paragraph_id": "p2", "paragraph_number": "3.2"},
        {"paragraph_id": "p3"},  # a paragraph without a number
        {"paragraph_id": "p4", "paragraph_number": "5.1"},
    ]
    assert mentioned_paragraphs(mentions) == ["3.2", "5.1"]
    doc = light_edge_doc(_row({"reason": "x", "mentions": mentions}))
    assert doc["meta"] == {"reason": "x", "paragraphs": ["3.2", "5.1"]}


def test_an_edge_that_keeps_its_paragraphs_keeps_them() -> None:
    doc = light_edge_doc(
        _row({"cited_ecli": "ECLI:NL:HR:2015:1", "paragraphs": ["4.3"]})
    )
    assert doc["meta"] == {"cited_ecli": "ECLI:NL:HR:2015:1", "paragraphs": ["4.3"]}
    assert light_edge_doc(_row({"mentions": []}))["meta"] == {}

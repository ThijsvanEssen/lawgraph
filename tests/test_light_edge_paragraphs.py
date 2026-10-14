"""The paragraphs a judgment cites in, on the edge of a neighbour (``_rows.light_edge_doc``):
taken from the mentions of an edge to an article, which a neighbour does not carry, and kept
as they are on an edge to a judgment."""

from __future__ import annotations

from lawgraph.db._rows import (
    PASSAGES_PER_EDGE,
    canvas_edge_doc,
    light_edge_doc,
    mentioned_paragraphs,
)


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


def _mention(
    paragraph_id: str, number: str | None, footnote: str | None = None
) -> dict:
    snippet = f"In {paragraph_id} wordt art. 6:162 BW genoemd."
    return {
        "paragraph_id": paragraph_id,
        "start": 110,
        "end": 123,
        "raw_match": "art. 6:162 BW",
        "snippet": snippet,
        "snippet_start": 110 - snippet.index("art."),
        "confidence": 0.95,
        **({"paragraph_number": number} if number else {}),
        **({"footnote": footnote} if footnote else {}),
    }


def test_with_passages_an_edge_gives_the_first_place_in_each_of_its_first_paragraphs() -> (
    None
):
    mentions = [
        _mention("rov-3.2", "3.2"),
        _mention("rov-3.2", "3.2"),  # a second place in the same paragraph
        _mention("rov-3.2", "3.2", footnote="4"),  # its footnote is a place of its own
        {
            "paragraph_id": "rov-4",
            "start": 0,
            "end": 3,
            "confidence": 0.9,
        },  # stored before
        _mention("rov-5.1", "5.1"),
        _mention("rov-6", None),  # past the first three
    ]
    row = _row({"reason": "x", "mentions": mentions})

    assert "passages" not in light_edge_doc(row)["meta"]
    passages = light_edge_doc(row, passages=True)["meta"]["passages"]

    assert [(p["paragraph_id"], p["footnote"]) for p in passages] == [
        ("rov-3.2", None),
        ("rov-3.2", "4"),
        ("rov-5.1", None),
    ]
    assert len(passages) == PASSAGES_PER_EDGE
    for passage in passages:
        assert passage["snippet"][passage["start"] : passage["end"]] == passage["text"]
    assert passages[0]["paragraph_number"] == "3.2"
    assert canvas_edge_doc(row, passages=True)["meta"]["passages"] == passages


def test_an_edge_whose_mentions_have_no_place_in_their_snippet_has_no_passages() -> (
    None
):
    stored = {k: v for k, v in _mention("rov-1", "1").items() if k != "snippet_start"}
    doc = light_edge_doc(_row({"mentions": [stored]}), passages=True)
    assert doc["meta"] == {"paragraphs": ["1"]}

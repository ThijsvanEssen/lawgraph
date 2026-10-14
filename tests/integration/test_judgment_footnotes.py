"""A citation a court makes in a footnote: the real ``normalize rechtspraak`` keeps the
footnotes of a judgment, ``semantic rechtspraak`` links what they cite, and a run in slices
names where the next one goes on."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.core.models import Node
from lawgraph.db import GraphStore, NodeWriter
from tests.integration.seed import write_judgments

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
ECLI = "ECLI:NL:RBZWB:2026:1134"
XML = (FIXTURES / "rechtspraak_rbzwb_2026_1134.xml").read_text()
BW10 = "BWBR0030068"


def _seed(store: GraphStore, xml: str | None = None) -> None:
    with NodeWriter(store) as nodes:
        nodes.add(
            Node(
                collection="instruments",
                key=BW10.lower(),
                labels=[],
                props={"bwb_id": BW10, "citation_title": "Burgerlijk Wetboek Boek 10"},
            )
        )
        nodes.add(
            Node(
                collection="articles",
                key=f"{BW10.lower()}_56",
                labels=[],
                props={"bwb_id": BW10, "article_number": "56"},
            )
        )
    write_judgments(store, {ECLI: xml or XML})


def test_a_citation_in_a_footnote_is_linked_for_its_paragraph(
    database: str, cli: Any
) -> None:
    store = GraphStore()
    _seed(store)

    sliced = cli("normalize", "rechtspraak", "--limit", "1")
    cli("semantic", "rechtspraak")

    assert "go on with --after" in sliced.stderr
    judgment = store.get_node("judgments", "ecli_nl_rbzwb_2026_1134")
    assert judgment is not None
    assert judgment.props["footnotes"] == [
        {
            "label": "1",
            "paragraph_id": "rov-3.1",
            "text": "Echtscheiding: art. 3 Brussel II-ter en art. 10:56 BW.",
            "at": 104,  # where its marker stands in r.o. 3.1
        }
    ]
    (meta,) = list(
        store.query(
            "SELECT doc -> 'meta' FROM edges WHERE from_id = %(j)s AND to_id = %(a)s"
            " AND relation = 'REFERS_TO'",
            {
                "j": "judgments/ecli_nl_rbzwb_2026_1134",
                "a": f"articles/{BW10.lower()}_56",
            },
        )
    )
    meta = meta if isinstance(meta, dict) else json.loads(meta)
    (mention,) = meta["mentions"]
    assert (mention["paragraph_id"], mention["footnote"], mention["raw_match"]) == (
        "rov-3.1",
        "1",
        "art. 10:56 BW",
    )


def test_a_cited_article_marks_its_words_in_the_snippet_of_its_footnote(
    database: str, cli: Any
) -> None:
    store = GraphStore()
    _seed(store)
    cli("normalize", "rechtspraak")
    cli("semantic", "rechtspraak")
    app.dependency_overrides[get_store] = lambda: store
    try:
        body = TestClient(app).get(f"/api/judgments/{ECLI}").json()
    finally:
        app.dependency_overrides.pop(get_store, None)

    (cited,) = body["cited_articles"]
    assert cited["snippet_paragraph_id"] == "rov-3.1"
    assert cited["snippet"] == "Echtscheiding: art. 3 Brussel II-ter en art. 10:56 BW."
    assert cited["snippet"][cited["start"] : cited["end"]] == cited["text"]
    assert cited["text"] == "art. 10:56 BW"


CITED = "ECLI:NL:HR:1988:AD5713"


def test_the_detail_serves_the_footnotes_with_what_they_cite(
    database: str, cli: Any
) -> None:
    """Urgenda cites its judgments in footnotes: the footnote is served with a span for the
    judgment and the article it cites, and the cited judgment says where it is cited."""
    note = "Echtscheiding: art. 3 Brussel II-ter en art. 10:56 BW."
    assert note in XML
    store = GraphStore()
    _seed(store, XML.replace(note, f"{note} Zie HR 23 september 1988, {CITED}."))
    cli("normalize", "rechtspraak")
    cli("semantic", "rechtspraak")
    cli("semantic", "rechtspraak-citations")
    app.dependency_overrides[get_store] = lambda: store
    try:
        body = TestClient(app).get(f"/api/judgments/{ECLI}").json()
    finally:
        app.dependency_overrides.pop(get_store, None)

    (footnote,) = body["judgment"]["footnotes"]
    assert (footnote["label"], footnote["paragraph_id"]) == ("1", "rov-3.1")
    (paragraph,) = [
        p for p in body["judgment"]["paragraphs"] if p["paragraph_id"] == "rov-3.1"
    ]
    # the marker stands after the last words of r.o. 3.1
    assert paragraph["text"][: footnote["at"]].endswith("van toepassing.")
    spans = {span["kind"]: span for span in footnote["citations"]}
    assert footnote["text"][spans["article"]["start"] : spans["article"]["end"]] == (
        "art. 10:56 BW"
    )
    judgment_span = spans["judgment"]
    assert footnote["text"][judgment_span["start"] : judgment_span["end"]] == CITED
    assert judgment_span["target"]["collection"] == "judgments"
    # a span of a footnote is not one of its paragraph
    assert paragraph["citations"] == []

    (cited,) = body["cited_judgments"]
    assert cited["ecli"] == CITED
    assert (cited["snippet_paragraph_id"], cited["footnote"]) == ("rov-3.1", "1")
    assert cited["paragraph_numbers"] == ["3.1"]
    assert cited["snippet"][cited["start"] : cited["end"]] == cited["text"] == CITED
    (article,) = body["cited_articles"]
    assert article["footnote"] == "1"

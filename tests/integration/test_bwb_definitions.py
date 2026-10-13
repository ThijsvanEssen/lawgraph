"""``semantic bwb-definitions`` for real: the stored toestanden of the Besluit zorgverzekering
and the Wft (articles of the XML the repository served) give their definitions in
``lg_instrument_definitions``, a full run in slices (``--limit``, ``--after``), and a
regulation whose toestand no longer defines anything loses its row."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lawgraph.config.constants import RAW_KIND_BWB_TOESTAND, SOURCE_BWB
from lawgraph.db import GraphStore, RawSourceWriter, raw_source_doc

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"


def _toestand(store: GraphStore, bwb_id: str, xml: str) -> None:
    with RawSourceWriter(store) as writer:
        writer.add(
            raw_source_doc(
                source=SOURCE_BWB,
                kind=RAW_KIND_BWB_TOESTAND,
                external_id=bwb_id,
                payload_text=xml,
                meta={"bwb_id": bwb_id},
            )
        )


def _kept(store: GraphStore) -> dict[str, list[dict[str, Any]]]:
    return {
        row["bwb_id"]: row["definitions"]
        for row in store.query(
            "SELECT bwb_id, definitions FROM lg_instrument_definitions"
        )
    }


def test_the_definitions_of_each_regulation_are_kept(database: str, cli: Any) -> None:
    store = GraphStore()
    _toestand(store, "BWBR0018492", (FIXTURES / "bwb_definitions_bzv.xml").read_text())
    _toestand(store, "BWBR0020368", (FIXTURES / "bwb_definitions_wft.xml").read_text())

    # a full run in two slices of one
    cli("semantic", "bwb-definitions", "--limit", "1")
    assert list(_kept(store)) == ["BWBR0018492"]
    cli("semantic", "bwb-definitions", "--after", "BWBR0018492", "--limit", "1")
    kept = _kept(store)
    assert sorted(kept) == ["BWBR0018492", "BWBR0020368"]
    wet = kept["BWBR0018492"][0]
    assert (wet["term"], wet["text"], wet["refers_to"]) == (
        "wet",
        "de Zorgverzekeringswet",
        "BWBR0018450",
    )
    assert len(kept["BWBR0020368"]) > 50
    (instrument,) = store.query(
        "SELECT instrument_id FROM lg_instrument_definitions WHERE bwb_id = 'BWBR0018492'"
    )
    assert instrument == "instruments/bwbr0018492"

    # a toestand that no longer defines anything
    _toestand(
        store,
        "BWBR0018492",
        '<toestand bwb-id="BWBR0018492"><wetgeving><wettekst><artikel label="Artikel 1">'
        "<kop><nr>1</nr></kop><al>Dit besluit treedt in werking.</al></artikel>"
        "</wettekst></wetgeving></toestand>",
    )
    cli("semantic", "bwb-definitions")
    assert list(_kept(store)) == ["BWBR0020368"]
    assert json.dumps(_kept(store)["BWBR0020368"][0]["scope"]) == json.dumps(
        {"kind": "wet", "path": ""}
    )


def test_an_article_marks_its_defined_terms_and_the_regulation_lists_them(
    database: str, cli: Any
) -> None:
    from fastapi.testclient import TestClient

    from lawgraph.api.app import app
    from lawgraph.api.dependencies import get_store
    from lawgraph.db.queries.definitions import article_terms

    store = GraphStore()
    _toestand(store, "BWBR0018492", (FIXTURES / "bwb_definitions_bzv.xml").read_text())
    cli("semantic", "bwb-definitions")
    text = (
        "Ter uitvoering van artikel 11, derde lid, van de wet heeft de verzekerde een "
        "eigen bijdrage. De wet geldt ook bij verblijf."
    )
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            {
                "_key": "bwbr0018492",
                "type": "instrument",
                "labels": ["BWB"],
                "props": {"bwb_id": "BWBR0018492", "title": "Besluit zorgverzekering"},
            }
        ],
    )
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            {
                "_key": "bwbr0018492_2",
                "type": "article",
                "labels": ["BWB"],
                "props": {
                    "bwb_id": "BWBR0018492",
                    "article_number": "2",
                    "text": text,
                    "path": "/Hoofdstuk2/Artikel2",
                },
            }
        ],
    )
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        listed = client.get("/api/instruments/BWBR0018492/definitions").json()
        article = client.get("/api/articles/BWBR0018492/2").json()
    finally:
        app.dependency_overrides.pop(get_store, None)

    assert [d["term"] for d in listed["definitions"]][:2] == ["wet", "verblijf"]
    assert listed["definitions"][0]["ref"] == "bwbr0018492_1:a:wet"
    marked = [
        (text[s["start"] : s["end"]], s["definition_ref"])
        for s in article["term_spans"]
    ]
    assert ("wet", "bwbr0018492_1:a:wet") in marked and (
        "verblijf",
        "bwbr0018492_1:b:verblijf",
    ) in marked
    assert ("eigen bijdrage", "bwbr0018492_1:c:eigen bijdrage") in marked
    assert {d["ref"] for d in article["definitions"]} >= {"bwbr0018492_1:a:wet"}

    # "van de wet" in a citation of the Zorgverzekeringswet: no span of its own, the
    # citation names the definition of "wet"; one of another law names none
    start = text.index("artikel 11")
    end = text.index("van de wet") + len("van de wet")
    spans, refs, _ = article_terms(
        store,
        "instruments/bwbr0018492",
        {"text": text, "path": "/Hoofdstuk2/Artikel2"},
        [(start, end, "BWBR0018450")],
    )
    assert refs == {0: "bwbr0018492_1:a:wet"}
    assert all(not (start <= s["start"] < end) for s in spans)
    _, other, _ = article_terms(
        store,
        "instruments/bwbr0018492",
        {"text": text, "path": "/Hoofdstuk2/Artikel2"},
        [(start, end, "BWBR0005537")],
    )
    assert other == {}


def test_each_term_of_an_unmarked_list_shows_its_own_definition(
    database: str, cli: Any
) -> None:
    """Cyberbeveiligingswet art. 1 is an unmarked list (every ``<li.nr>`` a dash): "entiteit"
    in art. 21 shows the definition of "entiteit", not of the first term of the article."""
    from fastapi.testclient import TestClient

    from lawgraph.api.app import app
    from lawgraph.api.dependencies import get_store

    store = GraphStore()
    _toestand(store, "BWBR0052872", (FIXTURES / "bwb_definitions_cbw.xml").read_text())
    cli("semantic", "bwb-definitions")
    text = (
        "De essentiële entiteit of belangrijke entiteit neemt maatregelen tegen de "
        "risico’s, naar de omvang van de entiteit."
    )
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            {
                "_key": "bwbr0052872",
                "type": "instrument",
                "labels": ["BWB"],
                "props": {"bwb_id": "BWBR0052872", "title": "Cyberbeveiligingswet"},
            }
        ],
    )
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            {
                "_key": "bwbr0052872_21",
                "type": "article",
                "labels": ["BWB"],
                "props": {
                    "bwb_id": "BWBR0052872",
                    "article_number": "21",
                    "text": text,
                    "path": "/Hoofdstuk7/Artikel21",
                },
            }
        ],
    )
    app.dependency_overrides[get_store] = lambda: store
    try:
        article = TestClient(app).get("/api/articles/BWBR0052872/21").json()
    finally:
        app.dependency_overrides.pop(get_store, None)

    by_ref = {d["ref"]: d for d in article["definitions"]}
    shown = [
        (text[s["start"] : s["end"]], by_ref[s["definition_ref"]]["term"])
        for s in article["term_spans"]
    ]
    assert shown == [
        ("essentiële entiteit", "essentiële entiteit"),
        ("belangrijke entiteit", "belangrijke entiteit"),
        ("risico", "risico"),
        ("entiteit", "entiteit"),
    ]
    assert {d["place"] for d in article["definitions"]} == {None}


def test_a_run_that_changes_definitions_raises_the_data_version(
    database: str, cli: Any
) -> None:
    """The article routes mark the terms with the kept definitions: a run that changes them
    changes the data version (and the ETag, and what the API keeps per version); one that
    changes nothing leaves it."""
    store = GraphStore()
    _toestand(store, "BWBR0047689", (FIXTURES / "bwb_definitions_jtf.xml").read_text())
    before = store.data_version()
    cli("semantic", "bwb-definitions")
    after = store.data_version()
    assert after != before
    assert {d["place"] for d in _kept(store)["BWBR0047689"]} == {None}
    cli("semantic", "bwb-definitions")
    assert store.data_version() == after

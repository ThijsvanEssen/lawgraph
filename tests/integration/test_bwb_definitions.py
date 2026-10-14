"""``semantic bwb-definitions`` for real: the stored toestanden of the Besluit zorgverzekering
and the Wft (articles of the XML the repository served) give their definitions in
``lg_instrument_definitions``, a full run in slices (``--limit``, ``--after``), and a
regulation whose toestand no longer defines anything loses its row."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from lawgraph.config.constants import (
    RAW_KIND_BWB_TOESTAND,
    RELATION_BASED_ON,
    SOURCE_BWB,
)
from lawgraph.db import GraphStore, RawSourceWriter, make_edge_doc, raw_source_doc

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
        {"kind": "wet", "path": "", "reach": "own_and_based"}
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


def _regulation(bwb_id: str, sentence: str, *terms: tuple[str, str]) -> str:
    """The toestand of a regulation whose art. 1 announces *terms* in an unmarked list."""
    items = "".join(
        f"<li><li.nr>–</li.nr><al><nadruk>{term}:</nadruk> {text};</al></li>"
        for term, text in terms
    )
    return (
        f'<toestand bwb-id="{bwb_id}"><wetgeving><wettekst>'
        '<artikel label="Artikel 1" bwb-ng-variabel-deel="/Artikel1"><kop><nr>1</nr></kop>'
        f'<al>{sentence}</al><lijst type="ongemarkeerd">{items}</lijst>'
        "</artikel></wettekst></wetgeving></toestand>"
    )


def test_a_regulation_marks_the_terms_of_the_law_it_is_issued_under(
    database: str, cli: Any
) -> None:
    """Cbw art. 1 defines its terms "in deze wet en de daarop berustende bepalingen": the
    Cyberbeveiligingsbesluit, issued under art. 16 of it, marks "CSIRT" with the definition
    of the Cbw, its own "wet" with its own; a regulation issued under art. 19 of the besluit
    takes both (two levels), its own definition of a term first. A regulation whose
    definitions hold "in deze regeling" alone gives none to the one under it."""
    from fastapi.testclient import TestClient

    from lawgraph.api.app import app
    from lawgraph.api.dependencies import get_store

    store = GraphStore()
    _toestand(store, "BWBR0052872", (FIXTURES / "bwb_definitions_cbw.xml").read_text())
    _toestand(
        store,
        "BWBR0052875",
        _regulation(
            "BWBR0052875",
            "In dit besluit en de daarop berustende bepalingen wordt verstaan onder:",
            ("wet", "Cyberbeveiligingswet"),
        ),
    )
    _toestand(
        store,
        "BWBR0052900",
        _regulation(
            "BWBR0052900",
            "In deze regeling wordt verstaan onder:",
            ("risico", "het risico van deze regeling"),
        ),
    )
    _toestand(
        store,
        "BWBR0052901",
        _regulation(
            "BWBR0052901",
            "In deze regeling wordt verstaan onder:",
            ("melding", "een melding"),
        ),
    )
    cli("semantic", "bwb-definitions")

    def instrument(bwb_id: str, title: str, **props: Any) -> dict[str, Any]:
        return {
            "_key": bwb_id.lower(),
            "type": "instrument",
            "labels": ["BWB"],
            "props": {
                "bwb_id": bwb_id,
                "title": title,
                "citation_title": title,
                **props,
            },
        }

    def article(bwb_id: str, number: str, path: str, text: str) -> dict[str, Any]:
        return {
            "_key": f"{bwb_id.lower()}_{number}",
            "type": "article",
            "labels": ["BWB"],
            "props": {
                "bwb_id": bwb_id,
                "article_number": number,
                "text": text,
                "path": path,
            },
        }

    cbb_text = "Het CSIRT informeert de essentiële entiteit over de wet."
    regeling_text = "Het CSIRT weegt het risico naar de wet."
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            instrument("BWBR0052872", "Cyberbeveiligingswet"),
            instrument("BWBR0052875", "Cyberbeveiligingsbesluit"),
            instrument("BWBR0052900", "Regeling melding"),
            instrument("BWBR0052901", "Regeling onder de regeling"),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            article("BWBR0052872", "16", "/Hoofdstuk3/Artikel16", "Er is een CSIRT."),
            article("BWBR0052875", "2", "/Artikel2", cbb_text),
            article("BWBR0052875", "19", "/Artikel19", "Bij regeling."),
            article("BWBR0052900", "3", "/Artikel3", regeling_text),
            article("BWBR0052900", "4", "/Artikel4", "Bij regeling."),
            article("BWBR0052901", "2", "/Artikel2", "Het risico van een CSIRT."),
        ],
    )
    store.bulk_insert_or_update_edges(
        [
            make_edge_doc(f"instruments/{regulation}", f"articles/{basis}",
                          RELATION_BASED_ON, source="bwb-grondslagen-linker")
            for regulation, basis in [
                ("bwbr0052875", "bwbr0052872_16"),
                ("bwbr0052900", "bwbr0052875_19"),
                ("bwbr0052901", "bwbr0052900_4"),
            ]
        ]
    )  # fmt: skip

    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        cbb = client.get("/api/articles/BWBR0052875/2").json()
        regeling = client.get("/api/articles/BWBR0052900/3").json()
        under = client.get("/api/articles/BWBR0052901/2").json()
        listed = client.get("/api/instruments/BWBR0052875/definitions").json()
    finally:
        app.dependency_overrides.pop(get_store, None)

    def marked(answer: dict[str, Any], text: str) -> list[tuple[str, str, str | None]]:
        by_ref = {d["ref"]: d for d in answer["definitions"]}
        return [
            (
                text[s["start"] : s["end"]],
                by_ref[s["definition_ref"]]["text"][:12],
                (by_ref[s["definition_ref"]]["given_by"] or {}).get("bwb_id"),
            )
            for s in answer["term_spans"]
        ]

    assert marked(cbb, cbb_text) == [
        ("CSIRT", "een Computer", "BWBR0052872"),
        ("essentiële entiteit", "een entiteit", "BWBR0052872"),
        ("wet", "Cyberbeveili", None),
    ]
    (csirt,) = [d for d in cbb["definitions"] if d["term"] == "CSIRT"]
    assert csirt["ref"] == "bwbr0052872_1:CSIRT"
    assert (csirt["article_number"], csirt["scope"]["reach"]) == ("1", "own_and_based")
    assert csirt["given_by"] == {
        "key": "bwbr0052872",
        "bwb_id": "BWBR0052872",
        "citation_title": "Cyberbeveiligingswet",
        "short_title": None,
        "abbreviation": None,
        "path": "/wetten/BWBR0052872",
    }
    # two levels: the Cbw through the besluit; its own "risico" first
    assert marked(regeling, regeling_text) == [
        ("CSIRT", "een Computer", "BWBR0052872"),
        ("risico", "het risico v", None),
        ("wet", "Cyberbeveili", "BWBR0052875"),
    ]
    # "In deze regeling": its "risico" holds in it alone; the Cbw is three levels up
    assert [s["term"] for s in under["term_spans"]] == []
    # the instrument lists its own alone
    assert [d["term"] for d in listed["definitions"]] == ["wet"]
    assert all(d["given_by"] is None for d in listed["definitions"])

"""The regulations issued under an article (`.../delegated`): a law whose article 16
delegates in two leden, an AMvB whose "Gelet op" names its first lid, a ministerial
regulation that names the whole article, and an AMvB on another article. `semantic
bwb-grondslagen` writes the BASED_ON edges from the regulations' `props.basis`."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_INSTRUMENT_VERSIONS,
    COLLECTION_INSTRUMENTS,
    RELATION_PART_OF,
    RELATION_REFERS_TO,
)
from lawgraph.core.models import Node, NodeType
from lawgraph.db import EdgeWriter, GraphStore, NodeWriter

WET = "BWBR0052872"
BESLUIT = "BWBR0052875"
REGELING = "BWBR0052878"
OTHER = "BWBR0052880"

_TEXT_16 = (
    "1. Bij of krachtens algemene maatregel van bestuur wordt het CSIRT aangewezen.\n"
    "2. Het CSIRT heeft taken.\n"
    "3. Bij algemene maatregel van bestuur worden regels gesteld over de scan."
)


def _parts(text: str) -> list[dict[str, Any]]:
    starts = [text.index(f"{n}. ") for n in (1, 2, 3)] + [len(text) + 1]
    return [
        {
            "id": f"lid-{n}",
            "kind": "lid",
            "number": f"{n}.",
            "start": starts[n - 1] + 3,
            "end": starts[n] - 1,
        }
        for n in (1, 2, 3)
    ]


def _instrument(bwb_id: str, kind: str, title: str, **props: Any) -> Node:
    # *kind* as `normalize bwb` stores it on prod: the `soort` of the toestand, `amvb`
    return Node(
        collection=COLLECTION_INSTRUMENTS,
        type=NodeType.INSTRUMENT,
        key=bwb_id.lower(),
        labels=["BWB"],
        props={
            "bwb_id": bwb_id,
            "kind": kind,
            "citation_title": title,
            "display_name": title,
            "source": "bwb",
            **props,
        },
    )


def _article(bwb_id: str, number: str, **props: Any) -> Node:
    return Node(
        collection=COLLECTION_ARTICLES,
        type=NodeType.ARTICLE,
        key=f"{bwb_id.lower()}_{number}",
        labels=["BWB"],
        props={
            "bwb_id": bwb_id,
            "article_number": number,
            "display_name": f"Artikel {number}",
            **props,
        },
    )


def _basis(article: str, text: str) -> dict[str, str]:
    return {
        "bwb_id": WET,
        "article": article,
        "doc": f"jci1.3:c:{WET}&artikel={article}",
        "text": text,
    }


def _seed(store: GraphStore) -> None:
    with NodeWriter(store) as writer:
        writer.add_all(
            [
                _instrument(WET, "wet", "Cyberbeveiligingswet"),
                _instrument(
                    BESLUIT,
                    "amvb",
                    "Cyberbeveiligingsbesluit",
                    basis=[_basis("16", "16, eerste lid"), _basis("17", "17")],
                ),
                _instrument(
                    REGELING,
                    "ministeriele-regeling",
                    "Cyberbeveiligingsregeling",
                    basis=[_basis("16", "16 van de Cyberbeveiligingswet")],
                ),
                _instrument(OTHER, "amvb", "Ander besluit", basis=[_basis("17", "17")]),
                _article(WET, "16", text=_TEXT_16, parts=_parts(_TEXT_16)),
                _article(WET, "17", text="Onze Minister wijst aan."),
                _article(
                    WET, "18", text="Bij ministeriële regeling worden regels gesteld."
                ),
                _article(BESLUIT, "2", position=2),
                _article(BESLUIT, "3", position=3),
                _article(BESLUIT, "4", position=4, repealed=True),
            ]
        )
    with EdgeWriter(store, what=None) as edges:
        for number in ("16", "17", "18"):
            edges.add(
                f"{COLLECTION_ARTICLES}/{WET.lower()}_{number}",
                f"{COLLECTION_INSTRUMENTS}/{WET.lower()}",
                RELATION_PART_OF,
                source="t",
            )
        for number, leden in (("3", ["1"]), ("2", []), ("4", ["1"])):
            edges.add(
                f"{COLLECTION_ARTICLES}/{BESLUIT.lower()}_{number}",
                f"{COLLECTION_ARTICLES}/{WET.lower()}_16",
                RELATION_REFERS_TO,
                source="t",
                meta={"leden": leden, "onderdelen": [], "aanhef": False},
            )


def _get(store: GraphStore, path: str) -> Any:
    app.dependency_overrides[get_store] = lambda: store
    try:
        response = TestClient(app).get(path)
    finally:
        app.dependency_overrides.pop(get_store, None)
    assert response.status_code == 200, response.text
    return response.json()


def test_the_regulations_issued_under_an_article(database: str, cli: Any) -> None:
    store = GraphStore()
    _seed(store)
    cli("semantic", "bwb-grondslagen")

    body = _get(store, f"/api/articles/{WET}/16/delegated")

    assert body["total"] == 2
    items = body["items"]
    # the AMvB first, then the ministerial regulation; not the AMvB on article 17
    assert [(i["instrument"]["bwb_id"], i["kind"], i["leden"]) for i in items] == [
        (BESLUIT, "amvb", ["1"]),
        (REGELING, "ministeriele-regeling", []),
    ]
    assert items[0]["text"] == "16, eerste lid"
    # its articles that refer to article 16, in its order; not the repealed one
    assert [(a["article_number"], a["leden"]) for a in items[0]["articles"]] == [
        ("2", []),
        ("3", ["1"]),
    ]
    assert items[1]["articles"] == []
    # lid 1 ("bij of krachtens"): the AMvB names it and the regulation names the whole
    # article; lid 3 ("bij"): an AMvB only, and the one there is names lid 1: none yet
    assert [(c["lid"], c["krachtens"], c["instruments"]) for c in body["clauses"]] == [
        ("1", True, [BESLUIT.lower(), REGELING.lower()]),
        ("3", False, []),
    ]


def test_the_article_says_where_it_delegates(database: str) -> None:
    store = GraphStore()
    _seed(store)

    article = _get(store, f"/api/articles/{WET}/16")
    clauses = article["delegations"]
    assert [(c["part"], c["kind"], c["text"]) for c in clauses] == [
        ("lid-1", "amvb", "Bij of krachtens algemene maatregel van bestuur"),
        ("lid-3", "amvb", "Bij algemene maatregel van bestuur"),
    ]
    text = article["article"]["text"]
    assert all(text[c["start"] : c["end"]] == c["text"] for c in clauses)
    assert _get(store, f"/api/articles/{WET}/17")["delegations"] == []


def test_a_basis_without_a_formula_and_a_formula_without_a_regulation(
    database: str, cli: Any
) -> None:
    store = GraphStore()
    _seed(store)
    cli("semantic", "bwb-grondslagen")

    # named as a basis, though its text has no formula: listed, by title
    body = _get(store, f"/api/articles/{WET}/17/delegated")
    assert [i["instrument"]["bwb_id"] for i in body["items"]] == [OTHER, BESLUIT]
    assert body["clauses"] == []
    # a formula no regulation fills yet
    body = _get(store, f"/api/articles/{WET}/18/delegated")
    assert (body["items"], body["total"]) == ([], 0)
    assert [(c["kind"], c["lid"], c["instruments"]) for c in body["clauses"]] == [
        ("ministeriele_regeling", None, [])
    ]

    app.dependency_overrides[get_store] = lambda: store
    try:
        missing = TestClient(app).get(f"/api/articles/{WET}/99/delegated")
    finally:
        app.dependency_overrides.pop(get_store, None)
    assert missing.status_code == 404


REPEALED = "BWBR0052881"
LATER = "BWBR0052882"
ON_REPEALED = "BWBR0052883"


def _version(bwb_id: str, valid_from: str, *, current: bool) -> Node:
    return Node(
        collection=COLLECTION_INSTRUMENT_VERSIONS,
        type=NodeType.INSTRUMENT_VERSION,
        key=f"{bwb_id.lower()}_{valid_from}",
        labels=["BWB"],
        props={"bwb_id": bwb_id, "valid_from": valid_from, "current": current},
    )


def _seed_in_force(store: GraphStore) -> None:
    """A repealed regulation on article 16, one in force on 16, 18 and the repealed
    article 19, and one in force on article 19 only."""
    with NodeWriter(store) as writer:
        writer.add_all(
            [
                # every version closed: repealed
                _instrument(
                    REPEALED, "AMvB", "Vervallen besluit", basis=[_basis("16", "16")]
                ),
                _version(REPEALED, "2020-01-01", current=False),
                # a version in force; its kind as the source writes it
                _instrument(
                    LATER,
                    "AMvB",
                    "Aanvullend besluit",
                    date_in_force="2026-01-01",
                    basis=[
                        _basis("18", "18"),
                        _basis("16", "16, derde lid"),
                        _basis("19", "19"),
                    ],
                ),
                _version(LATER, "2026-01-01", current=True),
                _version(LATER, "2025-01-01", current=False),
                _article(WET, "19", repealed=True),
                _instrument(
                    ON_REPEALED,
                    "ministeriele-regeling",
                    "Regeling op een vervallen artikel",
                    basis=[_basis("19", "19")],
                ),
                _version(ON_REPEALED, "2026-01-01", current=True),
            ]
        )


def test_a_repealed_regulation_is_not_issued_under_an_article(
    database: str, cli: Any
) -> None:
    store = GraphStore()
    _seed(store)
    _seed_in_force(store)
    cli("semantic", "bwb-grondslagen")

    body = _get(store, f"/api/articles/{WET}/16/delegated")

    # the repealed AMvB is left out, also from the clauses; the one in force is kept
    assert [i["instrument"]["bwb_id"] for i in body["items"]] == [
        LATER,
        BESLUIT,
        REGELING,
    ]
    assert REPEALED.lower() not in {
        k for c in body["clauses"] for k in c["instruments"]
    }


def test_the_regulations_issued_under_a_law(database: str, cli: Any) -> None:
    store = GraphStore()
    _seed(store)
    _seed_in_force(store)
    cli("semantic", "bwb-grondslagen")

    body = _get(store, f"/api/instruments/{WET}/delegated")

    # AMvBs by title, then the ministerial regulation; one row per regulation
    assert body["total"] == 4
    assert [(i["instrument"]["bwb_id"], i["kind"]) for i in body["items"]] == [
        (LATER, "amvb"),
        (OTHER, "amvb"),
        (BESLUIT, "amvb"),
        (REGELING, "ministeriele-regeling"),
    ]
    # not the repealed regulation, nor the one on a repealed article only
    later, _, besluit, regeling = body["items"]
    assert later["date_in_force"] == "2026-01-01"
    assert later["instrument"]["path"] == f"/wetten/{LATER}"
    # the articles in force of the law each names, in the order of the law, with its
    # leden: not the repealed article 19
    assert [(a["article_number"], a["leden"]) for a in later["articles"]] == [
        ("16", ["3"]),
        ("18", []),
    ]
    assert [
        (a["article_number"], a["text"], a["leden"]) for a in besluit["articles"]
    ] == [
        ("16", "16, eerste lid", ["1"]),
        ("17", "17", []),
    ]
    assert [a["key"] for a in regeling["articles"]] == [f"{WET.lower()}_16"]

    # a law no regulation is issued under, and an unknown one: empty, as the other lists
    # of an instrument
    for bwb_id in (REGELING, "BWBR0099999"):
        body = _get(store, f"/api/instruments/{bwb_id}/delegated")
        assert body == {"bwb_id": bwb_id, "total": 0, "items": []}

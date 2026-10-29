"""The regulations issued under an article (`.../delegated`): a law whose article 16
delegates in two leden, an AMvB whose "Gelet op" names its first lid, a ministerial
regulation that names the whole article, and an AMvB on another article. `semantic
bwb-grondslagen` writes the BASED_ON edges from the regulations' `props.basis`."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.api.schemas.instruments import SUB_DELEGATED_MAX
from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_INSTRUMENTS,
    RELATION_PART_OF,
    RELATION_REFERS_TO,
)
from lawgraph.core.models import Node
from lawgraph.db import EdgeWriter, GraphStore, NodeWriter
from tests.asserts import assert_status, show_items

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
    failing = [c for c in clauses if text[c["start"] : c["end"]] != c["text"]]
    assert not failing, show_items(failing)
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
    assert_status(missing, 404)


REPEALED = "BWBR0052881"
LATER = "BWBR0052882"
ON_REPEALED = "BWBR0052883"


def _seed_in_force(store: GraphStore) -> None:
    """A repealed regulation on article 16 (the BWB gives the first day it was no longer in
    force: ``date_expired``), one in force on 16, 18 and the repealed article 19 (it expires
    on a day still to come), and one in force on article 19 only."""
    with NodeWriter(store) as writer:
        writer.add_all(
            [
                # repealed: no longer in force from 1 January 2021
                _instrument(
                    REPEALED,
                    "AMvB",
                    "Vervallen besluit",
                    date_expired="2021-01-01",
                    basis=[_basis("16", "16")],
                ),
                # in force until a day to come; its kind as the source writes it
                _instrument(
                    LATER,
                    "AMvB",
                    "Aanvullend besluit",
                    date_in_force="2026-01-01",
                    date_expired="2999-01-01",
                    basis=[
                        _basis("18", "18"),
                        _basis("16", "16, derde lid"),
                        _basis("19", "19"),
                    ],
                ),
                _article(WET, "19", repealed=True),
                _instrument(
                    ON_REPEALED,
                    "ministeriele-regeling",
                    "Regeling op een vervallen artikel",
                    basis=[_basis("19", "19")],
                ),
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
        assert body == {
            "bwb_id": bwb_id,
            "total": 0,
            "expired_total": 0,
            "by_kind": {},
            "items": [],
        }


def test_the_regulations_no_longer_in_force_and_the_light_form(
    database: str, cli: Any
) -> None:
    store = GraphStore()
    _seed(store)
    _seed_in_force(store)
    cli("semantic", "bwb-grondslagen")

    default = _get(store, f"/api/instruments/{WET}/delegated")
    everything = _get(store, f"/api/instruments/{WET}/delegated?validity=all")
    gone = _get(store, f"/api/instruments/{WET}/delegated?validity=expired")
    light = _get(store, f"/api/instruments/{WET}/delegated?detail=summary")

    # the one no longer in force is counted, and shown when asked for, with its day
    assert default["expired_total"] == everything["expired_total"] == 1
    assert default["by_kind"] == {"amvb": 3, "ministeriele-regeling": 1}
    assert everything["total"] == default["total"] + 1
    assert [(i["instrument"]["bwb_id"], i["expired_on"]) for i in gone["items"]] == [
        (REPEALED, "2021-01-01")
    ]
    # one in force until a day to come carries that day
    assert {i["instrument"]["bwb_id"]: i["expired_on"] for i in default["items"]} == {
        LATER: "2999-01-01",
        **{
            i["instrument"]["bwb_id"]: None
            for i in default["items"]
            if i["instrument"]["bwb_id"] != LATER
        },
    }
    # the light form: the same regulations and articles, nothing of their own
    assert [i["instrument"]["bwb_id"] for i in light["items"]] == [
        i["instrument"]["bwb_id"] for i in default["items"]
    ]
    assert {k for i in light["items"] for a in i["articles"] for k in a} & {
        "referring"
    } == set()
    assert {k for i in light["items"] for k in i} & {"also_based_on"} == set()


def test_the_light_form_has_the_regulations_under_a_regulation(
    database: str, cli: Any
) -> None:
    store = GraphStore()
    _seed(store)
    _seed_chain(store)
    cli("semantic", "bwb-grondslagen")

    full = _get(store, f"/api/instruments/{WET}/delegated")
    light = _get(store, f"/api/instruments/{WET}/delegated?detail=summary")

    def under(body: dict[str, Any]) -> dict[str, list[tuple[str, str | None]]]:
        return {
            i["instrument"]["bwb_id"]: [
                (s["instrument"]["bwb_id"], s["expired_on"]) for s in i["sub_delegated"]
            ]
            for i in body["items"]
        }

    assert under(light) == under(full)
    assert under(light)[BESLUIT] == [(SUB, None)]
    sub = {i["instrument"]["bwb_id"]: i for i in light["items"]}[BESLUIT][
        "sub_delegated"
    ]
    assert [a["article_number"] for a in sub[0]["articles"]] == ["2", "3"]


def test_the_light_form_gives_the_first_regulations_under_a_regulation(
    database: str, cli: Any
) -> None:
    """A law under the Grondwet has dozens of regulations under it: the light form gives the
    first ``SUB_DELEGATED_MAX`` of them, in the order of the full form, and how many."""
    store = GraphStore()
    _seed(store)
    many = [f"BWBR00530{n:02d}" for n in range(SUB_DELEGATED_MAX + 1)]
    with NodeWriter(store) as writer:
        writer.add_all(
            _instrument(
                bwb_id,
                "ministeriele-regeling",
                f"Regeling {n:02d}",
                basis=[
                    {
                        "bwb_id": BESLUIT,
                        "article": "2",
                        "doc": f"jci1.3:c:{BESLUIT}&artikel=2",
                        "text": "artikel 2 van het Cyberbeveiligingsbesluit",
                    }
                ],
            )
            for n, bwb_id in enumerate(many)
        )
    cli("semantic", "bwb-grondslagen")

    full = _get(store, f"/api/instruments/{WET}/delegated")
    light = _get(store, f"/api/instruments/{WET}/delegated?detail=summary")

    def besluit(body: dict[str, Any]) -> dict[str, Any]:
        return next(i for i in body["items"] if i["instrument"]["bwb_id"] == BESLUIT)

    under = [s["instrument"]["bwb_id"] for s in besluit(full)["sub_delegated"]]
    assert under == many
    assert [s["instrument"]["bwb_id"] for s in besluit(light)["sub_delegated"]] == (
        many[:SUB_DELEGATED_MAX]
    )
    assert besluit(light)["sub_delegated_total"] == len(many)
    others = [i for i in light["items"] if i["instrument"]["bwb_id"] != BESLUIT]
    assert all(i["sub_delegated_total"] == 0 for i in others), show_items(others)


def test_the_basis_by_validity(database: str, cli: Any) -> None:
    store = GraphStore()
    _seed(store)
    _seed_in_force(store)
    cli("semantic", "bwb-grondslagen")

    body = _get(store, f"/api/instruments/{REPEALED}/basis?validity=all")

    assert body["expired_total"] == 0
    assert [i["instrument"]["bwb_id"] for i in body["items"]] == [WET]
    assert [i["expired_on"] for i in body["items"]] == [None]


SUB = "BWBR0052900"  # a ministerial regulation issued under the AMvB, not the law
WWKE = "BWBR0052871"  # another law the AMvB names


def _seed_chain(store: GraphStore) -> None:
    """The AMvB names article 7 of another law as well; a ministerial regulation is issued
    under its articles 2 and 3, and names the law nowhere in its preamble."""
    with NodeWriter(store) as writer:
        writer.add_all(
            [
                _instrument(
                    BESLUIT,
                    "amvb",
                    "Cyberbeveiligingsbesluit",
                    date_in_force="2026-08-15",
                    basis=[
                        _basis("16", "artikelen 16, eerste lid"),
                        _basis("17", "17 van de Cyberbeveiligingswet"),
                        {
                            "bwb_id": WWKE,
                            "article": "7",
                            "doc": f"jci1.3:c:{WWKE}&artikel=7",
                            "text": "artikel 7 van de Wet weerbaarheid kritieke entiteiten",
                        },
                    ],
                ),
                _instrument(WWKE, "wet", "Wet weerbaarheid kritieke entiteiten"),
                _article(
                    WWKE, "7", text="Bij ministeriële regeling worden regels gesteld."
                ),
                _instrument(
                    SUB,
                    "ministeriele-regeling",
                    "Regeling energiesector",
                    basis=[
                        {
                            "bwb_id": BESLUIT,
                            "article": "2",
                            "doc": f"jci1.3:c:{BESLUIT}&artikel=2",
                            "text": "artikelen 2 tot en met 3 van het Cyberbeveiligingsbesluit",
                        }
                    ],
                ),
                _article(SUB, "1", position=1),
            ]
        )
    with EdgeWriter(store, what=None) as edges:
        # the regulation refers to the law, not through a preamble
        edges.add(
            f"{COLLECTION_ARTICLES}/{SUB.lower()}_1",
            f"{COLLECTION_ARTICLES}/{WET.lower()}_16",
            RELATION_REFERS_TO,
            source="t",
            meta={"text": "artikel 16 van de wet", "leden": ["2"], "onderdelen": []},
        )


def test_a_law_gives_the_whole_basis_of_its_regulations(
    database: str, cli: Any
) -> None:
    store = GraphStore()
    _seed(store)
    _seed_chain(store)
    cli("semantic", "bwb-grondslagen")

    body = _get(store, f"/api/instruments/{WET}/delegated")
    by_id = {i["instrument"]["bwb_id"]: i for i in body["items"]}
    # the regulation issued under the AMvB is no item of the law
    assert SUB not in by_id
    besluit = by_id[BESLUIT]

    # article 16 delegates in the lid named, article 17 has no power: named only
    assert [
        (a["article_number"], a["text"], a["basis_kind"]) for a in besluit["articles"]
    ] == [("16", "16, eerste lid", "delegates"), ("17", "17", "mentioned")]
    assert besluit["basis_kind"] == "delegates"
    # the articles of the AMvB that work article 16 out, not the repealed one
    assert [
        (r["article_number"], r["leden"]) for r in besluit["articles"][0]["referring"]
    ] == [("2", []), ("3", ["1"])]
    assert besluit["articles"][1]["referring"] == []

    # the other law it names
    assert [
        (law["instrument"]["bwb_id"], law["kind"], [a["text"] for a in law["articles"]])
        for law in besluit["also_based_on"]
    ] == [(WWKE, "wet", ["7"])]

    # one level down: the ministerial regulation on its articles 2 and 3 (a range)
    (sub,) = besluit["sub_delegated"]
    assert (sub["instrument"]["bwb_id"], sub["kind"]) == (SUB, "ministeriele-regeling")
    assert [(a["article_number"], a["text"]) for a in sub["articles"]] == [
        ("2", "2 tot en met 3"),
        ("3", "2 tot en met 3"),
    ]
    # a regulation with only an article named, and one issued under the law directly
    assert by_id[OTHER]["basis_kind"] == "mentioned"
    assert by_id[REGELING]["sub_delegated"] == []


def test_a_regulation_gives_its_own_basis(database: str, cli: Any) -> None:
    store = GraphStore()
    _seed(store)
    _seed_chain(store)
    cli("semantic", "bwb-grondslagen")

    body = _get(store, f"/api/instruments/{BESLUIT}/basis")

    # per law, by title, with its articles in the order of the law
    assert [
        (i["instrument"]["bwb_id"], i["kind"], i["basis_kind"]) for i in body["items"]
    ] == [
        (WET, "wet", "delegates"),
        (WWKE, "wet", "delegates"),
    ]
    cbw = body["items"][0]
    assert [(a["article_number"], a["leden"]) for a in cbw["articles"]] == [
        ("16", ["1"]),
        ("17", []),
    ]
    assert [r["article_number"] for r in cbw["articles"][0]["referring"]] == ["2", "3"]
    assert body["total"] == 2

    # the ministerial regulation: on the AMvB; the law: none; an unknown one: none
    sub = _get(store, f"/api/instruments/{SUB}/basis")
    assert [i["instrument"]["bwb_id"] for i in sub["items"]] == [BESLUIT]
    for bwb_id in (WET, "BWBR0099999"):
        assert _get(store, f"/api/instruments/{bwb_id}/basis") == {
            "bwb_id": bwb_id,
            "total": 0,
            "expired_total": 0,
            "items": [],
        }


def test_related_laws_say_their_direction_and_basis(database: str, cli: Any) -> None:
    store = GraphStore()
    _seed(store)
    _seed_chain(store)
    cli("semantic", "bwb-grondslagen")

    body = _get(store, f"/api/instruments/{WET}/related-instruments")
    by_id = {i["bwb_id"]: i for i in body["items"]}
    # how many are one of a delegation, the same on a page of one
    based_on = sum(1 for i in body["items"] if i["based_on"])
    assert body["based_on_total"] == based_on >= 2
    page = _get(store, f"/api/instruments/{WET}/related-instruments?limit=1")
    assert (len(page["items"]), page["based_on_total"]) == (1, based_on)

    # two articles of the AMvB refer to one article of the law (the repealed one not)
    besluit = by_id[BESLUIT]
    assert (
        besluit["direction"],
        besluit["inbound_count"],
        besluit["inbound_cited_count"],
        besluit["outbound_count"],
    ) == ("inbound", 2, 1, 0)
    assert (besluit["kind"], besluit["date_in_force"]) == ("amvb", "2026-08-15")
    assert besluit["based_on"] is True
    assert besluit["basis"]["direction"] == "inbound"
    assert [a["article_number"] for a in besluit["basis"]["articles"]] == ["16", "17"]

    # issued under the AMvB, which is issued under the law
    sub = by_id[SUB]
    assert sub["based_on"] is True
    assert sub["basis"]["direction"] == "via"
    assert sub["basis"]["via"]["bwb_id"] == BESLUIT
    assert [a["article_number"] for a in sub["basis"]["articles"]] == ["2", "3"]

    # from the AMvB: the law it is issued under
    back = _get(store, f"/api/instruments/{BESLUIT}/related-instruments")
    (wet,) = [i for i in back["items"] if i["bwb_id"] == WET]
    assert (wet["direction"], wet["outbound_count"]) == ("outbound", 2)
    assert wet["basis"]["direction"] == "outbound"


def test_the_references_between_two_laws(database: str) -> None:
    store = GraphStore()
    _seed(store)
    _seed_chain(store)

    body = _get(store, f"/api/instruments/{WET}/references/{BESLUIT}")

    # inbound only, the referring article in its order; not the repealed article 4
    assert [
        (i["direction"], i["source"]["article_number"], i["target"]["article_number"])
        for i in body["items"]
    ] == [("inbound", "2", "16"), ("inbound", "3", "16")]
    assert body["items"][1]["leden"] == ["1"]
    assert body["total"] == 2
    back = _get(store, f"/api/instruments/{BESLUIT}/references/{WET}")
    assert [i["direction"] for i in back["items"]] == ["outbound", "outbound"]
    assert _get(store, f"/api/instruments/{WET}/references/{WET}")["items"] == []

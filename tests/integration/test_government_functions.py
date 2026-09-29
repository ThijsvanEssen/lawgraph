"""Cabinet posts on members: the real ``normalize rijksoverheid`` on stored pages, and the
member detail on its answer."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    COLLECTION_DOCUMENTS,
    COLLECTION_FACTIONS,
    COLLECTION_MEMBERS,
    RAW_KIND_RIJKSOVERHEID_CABINET,
    RAW_KIND_STCRT_POST_CREATORS,
    RELATION_AUTHORED,
    SOURCE_RIJKSOVERHEID,
    SOURCE_STAATSCOURANT,
)
from lawgraph.core.models import Node, NodeType, make_node_key
from lawgraph.db import (
    ArangoStore,
    EdgeWriter,
    NodeWriter,
    RawSourceWriter,
    raw_source_doc,
)


def page(name: str, sworn_in: str, *seats: tuple[str, list[str]]) -> str:
    """A cabinet page as Rijksoverheid writes one: title, introduction, ministers and the
    formatie block with the day of the beëdiging."""
    items = "".join(f"<li>{h}<br/>{'<br/>'.join(lines)}</li>" for h, lines in seats)
    return (
        f"<h1>Kabinet-{name}</h1>"
        f'<div class="rich-text larger-text"><p>Op {sworn_in} was de beëdiging van het '
        f"kabinet-{name}.</p></div>"
        f'<div class="rich-text"><h2>Ministers</h2><ul>{items}</ul></div>'
        f'<div class="rich-text"><h2>Kabinetsformatie</h2><ul>'
        f"<li>Beëdiging kabinet: {sworn_in}</li></ul></div>"
    )


def store_pages(store: ArangoStore, pages: dict[str, str]) -> None:
    with RawSourceWriter(store) as writer:
        for slug, html in pages.items():
            writer.add(
                raw_source_doc(
                    source=SOURCE_RIJKSOVERHEID,
                    kind=RAW_KIND_RIJKSOVERHEID_CABINET,
                    external_id=slug,
                    payload_text=html,
                    meta={
                        "url": f"https://example.org/{slug}",
                        "read_on": "2026-09-25",
                    },
                )
            )


def _member(
    key: str, name: str, family_name: str, birth_date: str, **props: Any
) -> Node:
    return Node(
        collection=COLLECTION_MEMBERS,
        type=NodeType.MEMBER,
        key=key,
        labels=["TK"],
        props={
            "name": name,
            "family_name": family_name,
            "birth_date": birth_date,
            **props,
        },
    )


def _get(store: ArangoStore, path: str) -> Any:
    app.dependency_overrides[get_store] = lambda: store
    try:
        return TestClient(app).get(path).json()
    finally:
        app.dependency_overrides.pop(get_store, None)


JETTEN = "49be3576_cea3_46c0_87eb_89beb108248d"
PAGES = {
    "kabinet-rutte-iv": page(
        "Rutte IV",
        "10 januari 2022",
        ("Minister voor Klimaat en Energie", ["R.A.A. (Rob) Jetten (D66)"]),
    ),
    "kabinet-jetten": page(
        "Jetten",
        "23 februari 2026",
        (
            "Minister-president, minister van Algemene Zaken",
            ["R.A.A. (Rob) Jetten MSc (D66)"],
        ),
        ("Minister van Financiën", ["P. (Piet) Lieftinck (VVD)"]),
    ),
}
D66 = {"short": "D66", "faction": None}


def test_a_member_gets_the_posts_of_the_holder_with_their_surname_and_initials(
    database: str, cli: Any
) -> None:
    store = ArangoStore()
    with NodeWriter(store) as writer:
        writer.add_all(
            [
                _member(JETTEN, "Rob Arnoldus Adrianus Jetten", "Jetten", "1987-03-25"),
                # the same surname, other initials: not him
                _member("other", "Karel Jetten", "Jetten", "1960-01-01"),
                # held a post before, holds none now: loses it
                _member(
                    "former",
                    "Oud",
                    "Oud",
                    "1950-01-01",
                    government_functions=[{"function": "minister"}],
                ),
            ]
        )
    store_pages(store, PAGES)

    cli("normalize", "rijksoverheid")

    jetten = _get(store, f"/api/members/{JETTEN}")
    assert jetten["government_name"] == "R.A.A. Jetten"
    assert [
        (f["cabinet_key"], f["seat"], f["from_date"], f["to_date"], f["party"])
        for f in jetten["government_functions"]
    ] == [
        (
            "rutte_iv",
            "-/minister_zonder_portefeuille/klimaat-en-energie",
            "2022-01-10",
            "2026-02-23",
            D66,
        ),
        ("jetten", "az/minister-president", "2026-02-23", None, D66),
    ]
    assert jetten["name"] == "Rob Arnoldus Adrianus Jetten"  # the rest is untouched
    assert _get(store, "/api/members/other")["government_functions"] == []
    assert _get(store, "/api/members/former")["government_functions"] == []

    # A holder no Tweede Kamer person fits is a member of their own ...
    own = make_node_key(SOURCE_RIJKSOVERHEID, "p lieftinck")
    alone = _get(store, f"/api/members/{own}")
    assert (alone["name"], alone["government_functions"][0]["cabinet_key"]) == (
        "P. Lieftinck",
        "jetten",
    )
    # ... until later data holds their Tweede Kamer person: then only that one.
    with NodeWriter(store) as writer:
        writer.add(_member("lieftinck", "Pieter Lieftinck", "Lieftinck", "1972-09-30"))
    cli("normalize", "rijksoverheid")
    assert _get(store, "/api/members/lieftinck")["government_functions"][0]["seat"] == (
        "fin/minister"
    )
    assert not store.has_node(COLLECTION_MEMBERS, own)


# A minister who never sat in parliament: the TK person has neither name nor date of birth.
VAN_WEEL = "9d0a1c34_0000_4000_8000_000000000001"
VAN_WEEL_ID = VAN_WEEL.replace("_", "-")


def test_a_minister_outside_parliament_is_found_by_signatures(
    database: str, cli: Any
) -> None:
    store = ArangoStore()
    function = "minister van Justitie en Veiligheid"
    with NodeWriter(store) as writer:
        writer.add_all(
            [
                Node(
                    collection=COLLECTION_MEMBERS,
                    type=NodeType.MEMBER,
                    key=VAN_WEEL,
                    labels=["TK"],
                    props={"external_id": VAN_WEEL_ID, "name": "", "display_name": ""},
                ),
                Node(
                    collection=COLLECTION_DOCUMENTS,
                    type=NodeType.DOCUMENT,
                    key="letter",
                    labels=["TK"],
                    props={
                        "date": "2024-10-01",
                        "actors": [
                            {
                                "person_id": VAN_WEEL_ID,
                                "name": "D.M. van Weel",
                                "function": function,
                                "capacity": "bewindspersoon",
                            }
                        ],
                    },
                ),
            ]
        )
    with EdgeWriter(store, what=None) as edges:
        edges.add(
            f"{COLLECTION_MEMBERS}/{VAN_WEEL}",
            f"{COLLECTION_DOCUMENTS}/letter",
            RELATION_AUTHORED,
            source="test",
            meta={
                "role": "Eerste ondertekenaar",
                "function": function,
                "capacity": "bewindspersoon",
            },
        )
    store_pages(
        store,
        {
            "kabinet-schoof": page(
                "Schoof",
                "2 juli 2024",
                (
                    "Minister van Justitie en Veiligheid",
                    ["D.M. (David) van Weel (VVD)"],
                ),
            )
        },
    )

    cli("normalize", "rijksoverheid")

    van_weel = _get(store, f"/api/members/{VAN_WEEL}")
    # no name of his own in the TK: the name Rijksoverheid gives, with the first name
    assert (van_weel["name"], van_weel["government_name"]) == (
        "David van Weel",
        "D.M. van Weel",
    )
    assert van_weel["government_functions"][0]["seat"] == "jenv/minister"


# ── The ministry of a post whose function names none ─────────────────────────

HOOGERVORST = "27b6eea7_b816_4d7c_b7dd_7f982a10a8b7"
ACHAHBAR = "achahbar"


def _signed(store: ArangoStore, member: str, key: str, day: str, function: str) -> None:
    with NodeWriter(store) as writer:
        writer.add(
            Node(
                collection=COLLECTION_DOCUMENTS,
                type=NodeType.DOCUMENT,
                key=key,
                labels=["TK"],
                props={"date": day},
            )
        )
    with EdgeWriter(store, what=None) as edges:
        edges.add(
            f"{COLLECTION_MEMBERS}/{member}",
            f"{COLLECTION_DOCUMENTS}/{key}",
            RELATION_AUTHORED,
            source="test",
            meta={"function": function, "capacity": "bewindspersoon"},
        )


def test_a_post_gets_its_ministry_from_the_official_sources(
    database: str, cli: Any
) -> None:
    store = ArangoStore()
    with NodeWriter(store) as writer:
        writer.add_all(
            [
                Node(
                    collection=COLLECTION_FACTIONS,
                    type=NodeType.FACTION,
                    key="vvd",
                    labels=["TK"],
                    props={"name": "VVD", "abbreviation": "VVD"},
                ),
                # the Tweede Kamer writes his initials without dots
                _member(
                    HOOGERVORST,
                    "Johannes Franciscus Hoogervorst",
                    "Hoogervorst",
                    "1956-04-19",
                    initials="JF",
                    faction_memberships=[{"faction_key": "vvd"}],
                ),
                _member(ACHAHBAR, "Nora Achahbar", "Achahbar", "1982-01-01"),
            ]
        )
    # a state secretary with a portfolio of her own signs as staatssecretaris van Financiën
    _signed(
        store, ACHAHBAR, "toeslagen", "2024-10-01", "staatssecretaris van Financiën"
    )
    # J.H. Hoogervorst on the page is J.F. in the Tweede Kamer: he signed as the minister
    _signed(
        store,
        HOOGERVORST,
        "vws",
        "2004-03-02",
        "minister van Volksgezondheid, Welzijn en Sport",
    )
    store_pages(
        store,
        {
            "kabinet-balkenende-ii": page(
                "Balkenende II",
                "27 mei 2003",
                (
                    "Minister van Volksgezondheid, Welzijn en Sport",
                    ["drs. J.H. Hoogervorst (VVD)"],
                ),
            ),
            "kabinet-rutte-iv": page(
                "Rutte IV",
                "10 januari 2022",
                ("Minister voor Klimaat en Energie", ["R.A.A. (Rob) Jetten (D66)"]),
            ),
            "kabinet-schoof": page(
                "Schoof",
                "2 juli 2024",
                ("Staatssecretaris Herstel en Toeslagen", ["N. (Nora) Achahbar (NSC)"]),
                ("Minister zonder Portefeuille", ["A.B. Iemand (VVD)"]),
            ),
        },
    )
    # the publications naming the Minister voor Klimaat en Energie (retrieve
    # staatscourant-posts)
    with RawSourceWriter(store) as writer:
        writer.add(
            raw_source_doc(
                source=SOURCE_STAATSCOURANT,
                kind=RAW_KIND_STCRT_POST_CREATORS,
                external_id="minister voor klimaat en energie|2022-01-10|2024-07-02",
                payload_json={
                    "creators": {
                        "Ministerie van Economische Zaken en Klimaat": 63,
                        "Ministerie van Infrastructuur en Waterstaat": 3,
                    }
                },
            )
        )

    done = cli("normalize", "rijksoverheid")

    posts = {
        row["function"]: row
        for row in store.query(
            "FOR m IN members FOR f IN m.props.government_functions OR [] "
            "RETURN MERGE(f, {member: m._key})"
        )
    }
    found = {
        function: (p["ministry"], p["ministry_source"], p["ministry_missing"])
        for function, p in posts.items()
    }
    assert found == {
        "Minister van Volksgezondheid, Welzijn en Sport": ("vws", "page", None),
        "Minister voor Klimaat en Energie": ("ezk", "staatscourant", None),
        "Staatssecretaris Herstel en Toeslagen": ("fin", "tk_signatures", None),
        "Minister zonder Portefeuille": (None, None, "no_source"),
    }
    # matched by what he signed, not made a member of his own
    assert posts["Minister van Volksgezondheid, Welzijn en Sport"]["member"] == (
        HOOGERVORST
    )
    assert "(1 by what they signed in government)" in done.stderr

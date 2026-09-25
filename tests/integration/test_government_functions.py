"""Cabinet posts on members: the real ``normalize wikidata`` on stored Wikidata records, and
the member detail on its answer."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    COLLECTION_DOCUMENTS,
    COLLECTION_MEMBERS,
    RAW_KIND_WIKIDATA_CABINET_POSTS,
    RELATION_AUTHORED,
    SOURCE_WIKIDATA,
)
from lawgraph.core.models import Node, NodeType
from lawgraph.db import (
    ArangoStore,
    EdgeWriter,
    NodeWriter,
    RawSourceWriter,
    raw_source_doc,
)

JETTEN = "49be3576_cea3_46c0_87eb_89beb108248d"
POSTS = [
    {
        "position_id": "Q110497984",
        "function": "Minister voor Klimaat en Energie",
        "cabinet_id": "Q110111120",
        "cabinet": "kabinet-Rutte IV",
        "from_date": "2022-01-10",
        "to_date": "2024-07-02",
    },
    {
        "position_id": "Q3058109",
        "function": "minister-president van Nederland",
        "cabinet_id": "Q137926983",
        "cabinet": "kabinet-Jetten",
        "from_date": "2026-02-23",
        "to_date": None,
    },
]


def _member(key: str, family_name: str, birth_date: str, **props: Any) -> Node:
    return Node(
        collection=COLLECTION_MEMBERS,
        type=NodeType.MEMBER,
        key=key,
        labels=["TK"],
        props={
            "name": key,
            "family_name": family_name,
            "birth_date": birth_date,
            **props,
        },
    )


def _store_people(store: ArangoStore, people: list[dict[str, Any]]) -> None:
    with RawSourceWriter(store) as writer:
        for person in people:
            writer.add(
                raw_source_doc(
                    source=SOURCE_WIKIDATA,
                    kind=RAW_KIND_WIKIDATA_CABINET_POSTS,
                    external_id=person["id"],
                    payload_json=person,
                )
            )


def _get(store: ArangoStore, path: str) -> Any:
    app.dependency_overrides[get_store] = lambda: store
    try:
        return TestClient(app).get(path).json()
    finally:
        app.dependency_overrides.pop(get_store, None)


def test_a_member_gets_the_posts_of_the_person_wikidata_ties_to_them(
    database: str, cli: Any
) -> None:
    store = ArangoStore()
    with NodeWriter(store) as writer:
        writer.add_all(
            [
                _member(JETTEN, "Jetten", "1987-03-25"),
                # born the same day, another name: not him
                _member("jansen", "Jansen", "1987-03-25"),
                # tied before, tied to nobody now: loses the posts
                _member(
                    "former",
                    "Oud",
                    "1950-01-01",
                    wikidata_id="Q1",
                    government_functions=[{"function": "minister"}],
                ),
            ]
        )
    person = {
        "id": "Q28860866",
        "name": "Rob Jetten",
        "birth_date": "1987-03-25",
        "birth_precision": 11,
        "posts": POSTS,
    }
    _store_people(store, [person])

    cli("normalize", "wikidata")

    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        jetten = client.get(f"/api/members/{JETTEN}").json()
        jansen = client.get("/api/members/jansen").json()
        former = client.get("/api/members/former").json()
    finally:
        app.dependency_overrides.pop(get_store, None)

    assert jetten["wikidata_id"] == "Q28860866"
    assert jetten["birth_date"] == "1987-03-25"
    assert [
        (f["function"], f["cabinet"], f["from_date"], f["to_date"])
        for f in jetten["government_functions"]
    ] == [
        (
            "Minister voor Klimaat en Energie",
            "kabinet-Rutte IV",
            "2022-01-10",
            "2024-07-02",
        ),
        ("minister-president van Nederland", "kabinet-Jetten", "2026-02-23", None),
    ]
    assert jetten["name"] == JETTEN  # the rest of the member is untouched
    assert jansen["government_functions"] == [] and jansen["wikidata_id"] is None
    assert former["government_functions"] == [] and former["wikidata_id"] is None


# A minister who never sat in parliament: the TK person has neither name nor date of birth.
OPSTELTEN = "9d0a1c34_0000_4000_8000_000000000001"
OPSTELTEN_ID = OPSTELTEN.replace("_", "-")
OPSTELTEN_POSTS = [
    {
        "position_id": "Q1",
        "function": "minister van Veiligheid en Justitie",
        "cabinet_id": "Q2",
        "cabinet": "kabinet-Rutte II",
        "from_date": "2012-11-05",
        "to_date": "2015-03-10",
    }
]
OLD_POSTS = [
    {
        "position_id": "Q3",
        "function": "minister van Financiën",
        "cabinet_id": "Q4",
        "cabinet": "kabinet-Drees I",
        "from_date": "1948-08-07",
        "to_date": "1951-03-15",
    }
]


def test_a_minister_is_found_by_signatures_and_a_person_without_one_stands_alone(
    database: str, cli: Any
) -> None:
    store = ArangoStore()
    with NodeWriter(store) as writer:
        writer.add_all(
            [
                Node(
                    collection=COLLECTION_MEMBERS,
                    type=NodeType.MEMBER,
                    key=OPSTELTEN,
                    labels=["TK"],
                    props={"external_id": OPSTELTEN_ID, "name": "", "display_name": ""},
                ),
                Node(
                    collection=COLLECTION_DOCUMENTS,
                    type=NodeType.DOCUMENT,
                    key="letter",
                    labels=["TK"],
                    props={
                        "date": "2013-05-01",
                        "actors": [
                            {
                                "person_id": OPSTELTEN_ID,
                                "name": "I.W. Opstelten",
                                "function": "minister van Veiligheid en Justitie",
                                "capacity": "bewindspersoon",
                            }
                        ],
                    },
                ),
            ]
        )
    with EdgeWriter(store, what=None) as edges:
        edges.add(
            f"{COLLECTION_MEMBERS}/{OPSTELTEN}",
            f"{COLLECTION_DOCUMENTS}/letter",
            RELATION_AUTHORED,
            source="test",
            meta={
                "role": "Eerste ondertekenaar",
                "function": "minister van Veiligheid en Justitie",
                "capacity": "bewindspersoon",
            },
        )
    old = {
        "id": "Q5",
        "name": "Piet Lieftinck",
        "birth_date": "1902-09-30",
        "birth_precision": 11,
        "posts": OLD_POSTS,
    }
    _store_people(
        store,
        [
            {
                "id": "Q6",
                "name": "Ivo Opstelten",
                "birth_date": "1944-08-31",
                "birth_precision": 11,
                "posts": OPSTELTEN_POSTS,
            },
            old,
        ],
    )

    cli("normalize", "wikidata")

    opstelten = _get(store, f"/api/members/{OPSTELTEN}")
    assert (opstelten["name"], opstelten["wikidata_id"]) == ("Ivo Opstelten", "Q6")
    assert opstelten["government_functions"][0]["cabinet"] == "kabinet-Rutte II"
    alone = _get(store, "/api/members/wikidata_q5")
    assert (alone["name"], alone["birth_date"], alone["wikidata_id"]) == (
        "Piet Lieftinck",
        "1902-09-30",
        "Q5",
    )
    assert alone["government_functions"][0]["cabinet"] == "kabinet-Drees I"

    # Later data holds his Tweede Kamer person: he is that member, and only that one.
    with NodeWriter(store) as writer:
        writer.add(_member("lieftinck", "Lieftinck", "1902-09-30"))
    cli("normalize", "wikidata")

    assert _get(store, "/api/members/lieftinck")["wikidata_id"] == "Q5"
    assert not store.has_node(COLLECTION_MEMBERS, "wikidata_q5")
    assert _get(store, f"/api/members/{OPSTELTEN}")["wikidata_id"] == "Q6"

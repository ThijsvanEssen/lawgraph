"""Cabinet posts on members: the real ``normalize wikidata`` on stored Wikidata records, and
the member detail on its answer."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    COLLECTION_MEMBERS,
    RAW_KIND_WIKIDATA_CABINET_POSTS,
    SOURCE_WIKIDATA,
)
from lawgraph.core.models import Node, NodeType
from lawgraph.db import ArangoStore, NodeWriter, RawSourceWriter, raw_source_doc

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
    with RawSourceWriter(store) as writer:
        writer.add(
            raw_source_doc(
                source=SOURCE_WIKIDATA,
                kind=RAW_KIND_WIKIDATA_CABINET_POSTS,
                external_id=person["id"],
                payload_json=person,
            )
        )

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

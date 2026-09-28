"""The judgment and instrument lists: what they hold, how they find and how they sort.

- A judgment known only because something cites it (a stub) is left out unless asked for.
- A query that is the whole of an ECLI or a case number finds that judgment only.
- A publication in the Staatsblad (``stb_2019_33``) is no regulation: it is out of the
  instrument list and counted apart in ``/api/stats``.
- The list sorts by the citation title, which a treaty has in full.
- An instrument counts what refers to it and to its articles.
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    RELATION_PART_OF,
    RELATION_REFERS_TO,
)
from lawgraph.core.bwb_xml import publication_props
from lawgraph.core.judgments import case_number_keys
from lawgraph.core.models import Node, NodeType, make_node_key
from lawgraph.db import ArangoStore, EdgeWriter, NodeWriter

TREATY_TITLE = "Verdrag " + "tot bescherming van de rechten van de mens " * 6


def _judgment(ecli: str, date: str | None, case_number: str | None, **props: Any):
    return Node(
        collection=COLLECTION_JUDGMENTS,
        type=NodeType.JUDGMENT,
        key=make_node_key(ecli),
        labels=[],
        props={
            "ecli": ecli,
            "display_name": ecli,
            "date": date,
            "date_eff": date,
            "case_number": case_number,
            "case_number_keys": case_number_keys(case_number),
            "summary": f"Uitspraak in zaak {case_number}",
            **props,
        },
    )


def _instrument(key: str, **props: Any) -> Node:
    return Node(
        collection=COLLECTION_INSTRUMENTS,
        type=NodeType.INSTRUMENT,
        key=key,
        labels=[],
        props=props,
    )


def _seed(store: ArangoStore) -> None:
    nodes = [
        _judgment("ECLI:NL:HR:2019:1278", "2019-07-19", "18/04298"),
        _judgment("ECLI:NL:PHR:2019:496", "2019-05-10", "18/04298"),
        # its summary names the case number of the other two
        _judgment("ECLI:NL:HR:2020:1", "2020-01-10", "19/00001"),
        _judgment("ECLI:EU:C:2026:243", None, None, stub=True),
        _instrument(
            "bwbr0001854",
            bwb_id="BWBR0001854",
            citation_title="Wetboek van Strafrecht",
            jurisdiction="nl",
        ),
        _instrument(
            "bwbr0005537",
            bwb_id="BWBR0005537",
            citation_title="Algemene wet bestuursrecht",
            jurisdiction="nl",
        ),
        _instrument(
            "verdrag_000001",
            title=TREATY_TITLE,
            citation_title=TREATY_TITLE,
            display_name=TREATY_TITLE[:200],
            jurisdiction="int",
            kind="verdrag",
        ),
        _instrument(
            "stb_2019_33",
            **publication_props(
                {"id": "stb-2019-33", "kind": "Stb", "year": 2019, "number": "33"}
            ),
        ),
        Node(
            collection=COLLECTION_ARTICLES,
            type=NodeType.ARTICLE,
            key="bwbr0001854_41",
            labels=[],
            props={"bwb_id": "BWBR0001854", "article_number": "41"},
        ),
    ]
    with NodeWriter(store) as writer:
        writer.add_all(nodes)
    with EdgeWriter(store, what=None) as edges:
        edges.add(
            "articles/bwbr0001854_41",
            "instruments/bwbr0001854",
            RELATION_PART_OF,
            source="t",
        )
        for judgment in ("ecli_nl_hr_2019_1278", "ecli_nl_hr_2020_1"):
            edges.add(
                f"judgments/{judgment}",
                "articles/bwbr0001854_41",
                RELATION_REFERS_TO,
                source="t",
            )
        edges.add(
            "judgments/ecli_nl_hr_2020_1",
            "instruments/bwbr0001854",
            RELATION_REFERS_TO,
            source="t",
        )


def _get(client: TestClient, path: str, **params: Any) -> Any:
    response = client.get(path, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_the_catalogue_lists_hold_find_and_sort_what_they_should(
    database: str, cli: Any
) -> None:
    store = ArangoStore()
    _seed(store)
    cli("semantic", "graph-list-stats")
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        judgments = _get(client, "/api/judgments", sort="date_asc")
        with_stubs = _get(client, "/api/judgments", include_stubs="true")
        by_ecli = _get(client, "/api/judgments", q="ECLI:NL:HR:2019:1278")
        by_case = _get(client, "/api/judgments", q="18/04298")
        instruments = _get(client, "/api/instruments", sort="title")
        publications = _get(client, "/api/instruments", kind="publicatie")
        strafrecht = _get(client, "/api/instruments/BWBR0001854")
        stats = _get(client, "/api/stats")
    finally:
        app.dependency_overrides.pop(get_store, None)

    assert judgments["total"] == 3
    assert (
        judgments["items"][0]["ecli"] == "ECLI:NL:PHR:2019:496"
    )  # oldest, not the stub
    assert with_stubs["total"] == 4
    assert [j["ecli"] for j in by_ecli["items"]] == ["ECLI:NL:HR:2019:1278"]
    assert {j["ecli"] for j in by_case["items"]} == {
        "ECLI:NL:HR:2019:1278",
        "ECLI:NL:PHR:2019:496",
    }

    assert [i["key"] for i in instruments["items"]] == [
        "bwbr0005537",
        "verdrag_000001",
        "bwbr0001854",
    ]
    assert instruments["total"] == 3
    assert instruments["items"][1]["citation_title"] == TREATY_TITLE
    assert [i["key"] for i in publications["items"]] == ["stb_2019_33"]

    # one reference to the law, two to its article 41
    assert strafrecht["inbound_citation_count"] == 3
    assert (stats["nodes"]["instruments"], stats["nodes"]["publications"]) == (3, 1)

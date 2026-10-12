"""The Kamerstukken a paper's subject names: the real ``normalize tk-dossiers`` and
``semantic tk-cited-papers``, then the API.

- A letter of the government with a case of its own (no Zaak links it to the motions) says
  "Uitvoering van de motie … (Kamerstuk 25424-795) en de motie … (Kamerstuk 29282-638)":
  ``ANSWERS`` to both motions.
- A list of questions names a letter "(Kamerstuk 21501-02-3465)" (a dossier with a numeric
  suffix) and a paper that is not in the graph: ``REFERS_TO`` the letter, nothing else.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    RAW_KIND_TK_DOCUMENT,
    RAW_KIND_TK_DOSSIER,
    SOURCE_TK,
)
from lawgraph.db import GraphStore, RawSourceWriter, raw_source_doc
from tests.integration.seed import uid

MOTION_A, MOTION_B, LETTER, AGENDA, QUESTIONS = (uid(n, 21) for n in range(1, 6))
DOSSIERS = [
    {"Id": uid(1, 22), "Nummer": 25424, "Toevoeging": None},
    {"Id": uid(2, 22), "Nummer": 29282, "Toevoeging": None},
    {"Id": uid(3, 22), "Nummer": 21501, "Toevoeging": "02"},
]


def _paper(
    guid: str, kind: str, subject: str, dossier: dict[str, Any] | None, sequence: int
) -> dict[str, Any]:
    return {
        "Id": guid,
        "DocumentNummer": f"2026D{sequence:05d}",
        "Soort": kind,
        "Onderwerp": subject,
        "Datum": "2026-06-30T00:00:00+02:00",
        "Volgnummer": sequence,
        "Kamerstukdossier": [dossier] if dossier else [],
    }


PAPERS = [
    _paper(MOTION_A, "Motie", "Motie van het lid Vliegenthart c.s.", DOSSIERS[0], 795),
    _paper(
        MOTION_B, "Motie", "Motie van het lid Diederik van Dijk c.s.", DOSSIERS[1], 638
    ),
    _paper(
        LETTER,
        "Brief regering",
        "Uitvoering van de motie van het lid Vliegenthart c.s. over een plan "
        "(Kamerstuk 25424-795) en de motie van het lid Diederik van Dijk c.s. over steun "
        "(Kamerstuk 29282-638)",
        None,
        -1,
    ),
    _paper(AGENDA, "Brief regering", "Geannoteerde agenda", DOSSIERS[2], 3465),
    _paper(
        QUESTIONS,
        "Lijst van vragen",
        "Lijst van vragen over de geannoteerde agenda (Kamerstuk 21501-02-3465) en "
        "over een brief (Kamerstuk 31015-999)",
        None,
        -1,
    ),
]


def _id(guid: str) -> str:
    return "documents/" + guid.lower().replace("-", "_")


def _edges(store: GraphStore) -> dict[tuple[str, str, str], Any]:
    rows = store.query(
        "SELECT from_id, relation, to_id, doc -> 'meta' AS meta FROM edges"
        " WHERE source = 'tk-cited-papers'"
    )
    return {(r["from_id"], r["relation"], r["to_id"]): r["meta"] for r in rows}


@pytest.fixture()
def store(database: str, cli: Any) -> GraphStore:
    store = GraphStore()
    records = [(RAW_KIND_TK_DOSSIER, {**d, "Titel": "Dossier"}) for d in DOSSIERS]
    records += [(RAW_KIND_TK_DOCUMENT, paper) for paper in PAPERS]
    with RawSourceWriter(store) as writer:
        for kind, payload in records:
            writer.add(
                raw_source_doc(
                    source=SOURCE_TK,
                    kind=kind,
                    external_id=payload["Id"],
                    payload_json=payload,
                )
            )
    cli("normalize", "tk-dossiers")
    cli("semantic", "tk-cited-papers")
    return store


EXPECTED = {
    (_id(LETTER), "ANSWERS", _id(MOTION_A)): {"basis": "subject", "text": "25424-795"},
    (_id(LETTER), "ANSWERS", _id(MOTION_B)): {"basis": "subject", "text": "29282-638"},
    (_id(QUESTIONS), "REFERS_TO", _id(AGENDA)): {
        "basis": "subject",
        "text": "21501-02-3465",
    },
}


def test_the_papers_a_subject_names(store: GraphStore) -> None:
    assert _edges(store) == EXPECTED


def test_a_second_run_and_a_run_since_change_nothing(
    store: GraphStore, cli: Any
) -> None:
    cli("semantic", "tk-cited-papers")
    cli("semantic", "tk-cited-papers", "--since", "1d")
    assert _edges(store) == EXPECTED


def _subject(store: GraphStore, guid: str, subject: str) -> None:
    store.execute(
        "UPDATE documents SET props = (props::jsonb || %(subject)s::jsonb)::json"
        " WHERE id = %(id)s",
        {"subject": json.dumps({"subject": subject}), "id": _id(guid)},
    )


@pytest.mark.parametrize("since", [("--since", "1d"), ()])
def test_an_edge_no_longer_named_goes(
    store: GraphStore, cli: Any, since: tuple[str, ...]
) -> None:
    _subject(store, LETTER, "Uitvoering van de motie (Kamerstuk 25424-795)")
    _subject(store, QUESTIONS, "Lijst van vragen over de geannoteerde agenda")
    cli("semantic", "tk-cited-papers", *since)
    assert set(_edges(store)) == {(_id(LETTER), "ANSWERS", _id(MOTION_A))}


@pytest.fixture()
def client(store: GraphStore) -> Iterator[TestClient]:
    app.dependency_overrides[get_store] = lambda: store
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(get_store, None)


def _bucket(client: TestClient, guid: str, relation: str, direction: str) -> list[str]:
    key = guid.lower().replace("-", "_")
    body = client.get(f"/api/nodes/documents/{key}").json()
    return sorted(
        item["id"]
        for bucket in body["neighbors"]["buckets"]
        if (bucket["relation"], bucket["direction"], bucket["collection"])
        == (relation, direction, "documents")
        for item in bucket["items"]
    )


def test_both_papers_show_the_edge(client: TestClient) -> None:
    assert _bucket(client, LETTER, "ANSWERS", "outbound") == sorted(
        [_id(MOTION_A), _id(MOTION_B)]
    )
    assert _bucket(client, MOTION_A, "ANSWERS", "inbound") == [_id(LETTER)]
    assert _bucket(client, AGENDA, "REFERS_TO", "inbound") == [_id(QUESTIONS)]

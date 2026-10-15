"""The Kamerstukken a paper's subject names: the real ``normalize tk-dossiers`` and
``semantic tk-cited-papers``, then the API.

- A letter of the government with a case of its own (no Zaak links it to the motions) says
  "Uitvoering van de motie … (Kamerstuk 25424-795) en de motie … (Kamerstuk 29282-638)":
  ``ANSWERS`` to both motions.
- A list of questions names a letter "(Kamerstuk 21501-02-3465)" (a dossier with a numeric
  suffix) and a paper that is not in the graph: ``REFERS_TO`` the letter, nothing else.
- A letter on moties names one in its subject and, in its text (``normalize tk-content``),
  the same one in a footnote, another "(29282, nr. 638)" after "motie" and the agenda: one
  ``ANSWERS`` per motion, the subject's from the subject, the other from the text; none to
  the agenda, which is no motion.
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
    RAW_KIND_TK_KAMERSTUK_XML,
    SOURCE_TK,
)
from lawgraph.db import GraphStore, RawSourceWriter, raw_source_doc
from tests.integration.seed import uid, write_tk

MOTION_A, MOTION_B, LETTER, AGENDA, QUESTIONS, ON_MOTIONS = (
    uid(n, 21) for n in range(1, 7)
)
DOSSIERS = [
    {"Id": uid(1, 22), "Nummer": 25424, "Toevoeging": None},
    {"Id": uid(2, 22), "Nummer": 29282, "Toevoeging": None},
    {"Id": uid(3, 22), "Nummer": 21501, "Toevoeging": "02"},
]


def _document(
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


DOCUMENTS = [
    _document(
        MOTION_A, "Motie", "Motie van het lid Vliegenthart c.s.", DOSSIERS[0], 795
    ),
    _document(
        MOTION_B, "Motie", "Motie van het lid Diederik van Dijk c.s.", DOSSIERS[1], 638
    ),
    _document(
        LETTER,
        "Brief regering",
        "Uitvoering van de motie van het lid Vliegenthart c.s. over een plan "
        "(Kamerstuk 25424-795) en de motie van het lid Diederik van Dijk c.s. over steun "
        "(Kamerstuk 29282-638)",
        None,
        -1,
    ),
    _document(AGENDA, "Brief regering", "Geannoteerde agenda", DOSSIERS[2], 3465),
    _document(
        ON_MOTIONS,
        "Brief regering",
        "Uitvoering van de motie van het lid Vliegenthart c.s. (Kamerstuk 25424-795) en "
        "andere moties",
        DOSSIERS[0],
        800,
    ),
    _document(
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


# The text of the letter on moties: the motion of its subject again in a footnote, another
# in brackets after "motie", and the agenda, a letter.
ON_MOTIONS_XML = (
    "<officiele-publicatie><kamerstuk><stuk>"
    '<tussenkop kopopmaak="vet">Motie Vliegenthart over een plan</tussenkop>'
    "<al>Uw Kamer heeft met de motie van het lid Vliegenthart (GL-PvdA)"
    '<noot id="n1" type="voet"><noot.nr>1</noot.nr><noot.al>Kamerstuk '
    '<extref doc="kst-25424-795">25 424, nr. 795</extref></noot.al></noot>'
    " de regering verzocht een plan te maken.</al>"
    "<al>In lijn met de motie-Van Dijk (29282, nr. 638) en de geannoteerde agenda "
    "(Kamerstuk 21501-02, nr. 3465) wordt gewerkt.</al>"
    "</stuk></kamerstuk></officiele-publicatie>"
)


@pytest.fixture()
def store(database: str, cli: Any) -> GraphStore:
    store = GraphStore()
    records = [(RAW_KIND_TK_DOSSIER, {**d, "Titel": "Dossier"}) for d in DOSSIERS]
    records += [(RAW_KIND_TK_DOCUMENT, paper) for paper in DOCUMENTS]
    write_tk(store, records)
    with RawSourceWriter(store) as writer:
        writer.add(
            raw_source_doc(
                source=SOURCE_TK,
                kind=RAW_KIND_TK_KAMERSTUK_XML,
                external_id="kst-25424-800",
                payload_text=ON_MOTIONS_XML,
                meta={"document": _id(ON_MOTIONS).partition("/")[2]},
            )
        )
    cli("normalize", "tk-dossiers")
    cli("normalize", "tk-content")
    cli("semantic", "tk-cited-papers")
    return store


# An answer quotes the whole subject: what the letter says it does with the motion.
_LETTER_SUBJECT = DOCUMENTS[2]["Onderwerp"]
EXPECTED = {
    (_id(LETTER), "ANSWERS", _id(MOTION_A)): {
        "basis": "subject",
        "text": _LETTER_SUBJECT,
        "reference": "25424-795",
    },
    (_id(LETTER), "ANSWERS", _id(MOTION_B)): {
        "basis": "subject",
        "text": _LETTER_SUBJECT,
        "reference": "29282-638",
    },
    (_id(QUESTIONS), "REFERS_TO", _id(AGENDA)): {
        "basis": "subject",
        "text": "21501-02-3465",
        "reference": "21501-02-3465",
    },
    # named by the subject: from the subject, not again from the footnote
    (_id(ON_MOTIONS), "ANSWERS", _id(MOTION_A)): {
        "basis": "subject",
        "text": DOCUMENTS[4]["Onderwerp"],
        "reference": "25424-795",
    },
    # named in the text alone
    (_id(ON_MOTIONS), "ANSWERS", _id(MOTION_B)): {
        "basis": "text",
        "text": "In lijn met de motie-Van Dijk (29282, nr. 638) en de geannoteerde agenda "
        "(Kamerstuk 21501-02, nr. 3465) wordt gewerkt.",
        "reference": "29282, nr. 638",
    },
}


def _confidence(store: GraphStore, guid: str, other: str) -> float:
    (row,) = store.query(
        "SELECT confidence FROM edges WHERE from_id = %(a)s AND to_id = %(b)s"
        " AND relation = 'ANSWERS'",
        {"a": _id(guid), "b": _id(other)},
    )
    return float(row)


def test_the_papers_a_subject_names(store: GraphStore) -> None:
    assert _edges(store) == EXPECTED
    # an answer read from the text is less sure than one its subject states
    assert _confidence(store, ON_MOTIONS, MOTION_A) == 1.0
    assert _confidence(store, ON_MOTIONS, MOTION_B) == 0.9


def test_a_motion_named_in_a_footnote_alone_is_answered(
    store: GraphStore, cli: Any
) -> None:
    """The footnote is where a letter names most motions: without the subject naming it,
    the footnote gives the answer."""
    _subject(store, ON_MOTIONS, "Uitvoering van moties")
    cli("semantic", "tk-cited-papers")
    edges = _edges(store)
    assert edges[(_id(ON_MOTIONS), "ANSWERS", _id(MOTION_A))] == {
        "basis": "footnote",
        "text": "Kamerstuk 25 424, nr. 795",
        "reference": "25 424, nr. 795",
    }
    assert (_id(ON_MOTIONS), "ANSWERS", _id(MOTION_B)) in edges
    assert (_id(ON_MOTIONS), "REFERS_TO", _id(AGENDA)) not in edges


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


def _text(store: GraphStore, guid: str, text: str) -> None:
    store.execute(
        "UPDATE documents SET props = (props::jsonb || %(text)s::jsonb)::json"
        " WHERE id = %(id)s",
        {"text": json.dumps({"text": text, "footnotes": []}), "id": _id(guid)},
    )


@pytest.mark.parametrize("since", [("--since", "1d"), ()])
def test_an_edge_no_longer_named_goes(
    store: GraphStore, cli: Any, since: tuple[str, ...]
) -> None:
    _subject(store, LETTER, "Uitvoering van de motie (Kamerstuk 25424-795)")
    _subject(store, QUESTIONS, "Lijst van vragen over de geannoteerde agenda")
    _subject(store, ON_MOTIONS, "Uitvoering van moties")
    _text(store, ON_MOTIONS, "Over de moties volgt later een brief.")
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
    assert _bucket(client, MOTION_A, "ANSWERS", "inbound") == sorted(
        [_id(LETTER), _id(ON_MOTIONS)]
    )
    assert _bucket(client, AGENDA, "REFERS_TO", "inbound") == [_id(QUESTIONS)]

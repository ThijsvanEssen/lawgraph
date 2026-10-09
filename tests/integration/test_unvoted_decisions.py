"""A withdrawn amendment on a real database: its Besluit ``Stemmen - ingetrokken``, which no
Stemming carries (``fetch_bill_decisions(without_votes=True)``), is a decision on its case
without an outcome, and its case says the Kamer is done with it (``Zaak.Afgedaan``). An
amendment still open says so too. The records have the fields the API sends."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    RAW_KIND_TK_BESLUIT,
    RAW_KIND_TK_DOCUMENT,
    RAW_KIND_TK_DOSSIER,
    RAW_KIND_TK_ZAAK,
    SOURCE_TK,
)
from lawgraph.core.models import make_node_key
from lawgraph.db import GraphStore, RawSourceWriter, raw_source_doc
from tests.integration.seed import uid

NUMBER = 36496
DOSSIER = {
    "Id": uid(NUMBER, 3),
    "Titel": "Wet betaalbare huur",
    "Nummer": NUMBER,
    "Toevoeging": None,
    "Kamer": "Tweede Kamer",
    "Afgesloten": False,
    "Verwijderd": False,
}


def _zaak(salt: int, done: bool) -> dict[str, Any]:
    return {
        "Id": uid(NUMBER, salt),
        "Soort": "Amendement",
        "Nummer": f"2024Z0{salt}",
        "Onderwerp": f"Amendement {salt} over het overgangsrecht",
        "Afgedaan": done,
        "Verwijderd": False,
        "Kamerstukdossier": [{"Id": uid(NUMBER, 3), "Nummer": NUMBER}],
    }


WITHDRAWN, OPEN, REJECTED = _zaak(60, True), _zaak(61, False), _zaak(62, True)


def _paper(case: dict[str, Any], sequence: int) -> dict[str, Any]:
    return {
        "Id": uid(NUMBER, 100 + sequence),
        "Soort": "Amendement",
        "Titel": "Wet betaalbare huur",
        "Onderwerp": case["Onderwerp"],
        "Datum": "2024-04-24T00:00:00+02:00",
        "Volgnummer": sequence,
        "Zaak": [case],
        "DocumentActor": [],
    }


def _besluit(salt: int, case: dict[str, Any], kind: str, text: str) -> dict[str, Any]:
    return {
        "Id": uid(NUMBER, salt),
        "BesluitSoort": kind,
        "BesluitTekst": text,
        "AgendapuntZaakBesluitVolgorde": 1,
        "Verwijderd": False,
        "Zaak": [case],
        "Agendapunt": {
            "Onderwerp": case["Onderwerp"],
            "Activiteit": {"Soort": "Stemmingen", "Datum": "2024-04-25T15:00:00"},
            "Zaak": [case],
        },
    }


WITHDRAWAL = _besluit(7, WITHDRAWN, "Stemmen - ingetrokken", "Ingetrokken.")
# a vote with an outcome, for the list beside it
REJECTION = _besluit(8, REJECTED, "Stemmen - verworpen", "Verworpen.")


@pytest.fixture()
def store(database: str, cli: Any) -> Iterator[GraphStore]:
    store = GraphStore()
    records = [
        (RAW_KIND_TK_DOSSIER, DOSSIER),
        (RAW_KIND_TK_ZAAK, WITHDRAWN),
        (RAW_KIND_TK_ZAAK, OPEN),
        (RAW_KIND_TK_DOCUMENT, _paper(WITHDRAWN, 60)),
        (RAW_KIND_TK_DOCUMENT, _paper(OPEN, 61)),
        (RAW_KIND_TK_ZAAK, REJECTED),
        (RAW_KIND_TK_DOCUMENT, _paper(REJECTED, 62)),
        (RAW_KIND_TK_BESLUIT, WITHDRAWAL),
        (RAW_KIND_TK_BESLUIT, REJECTION),
    ]
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
    cli("normalize", "tk")
    cli("normalize", "tk-dossiers")
    yield store


def test_a_withdrawn_amendment_has_its_decision_and_an_open_one_none(
    store: GraphStore,
) -> None:
    case = f"cases/{make_node_key(WITHDRAWN['Id'])}"
    (decision,) = store.query(
        "SELECT json_build_object('id', id, 'props', props) FROM decisions"
        " WHERE passed IS NULL"
    )
    props = decision["props"]
    assert props["decision_kind"] == "Stemmen - ingetrokken"
    assert props.get("passed") is None  # no outcome: it never came to a vote
    assert props["primary_case_id"] == WITHDRAWN["Id"]
    about = list(
        store.query(
            "SELECT to_id FROM edges WHERE from_id = %(id)s AND relation = 'ABOUT'",
            {"id": decision["id"]},
        )
    )
    assert case in about

    done = {
        row["key"]: row["done"]
        for row in store.query(
            "SELECT json_build_object('key', key, 'done', props -> 'done') FROM cases"
        )
    }
    assert done == {
        make_node_key(WITHDRAWN["Id"]): True,
        make_node_key(OPEN["Id"]): False,
        make_node_key(REJECTED["Id"]): True,
    }


def test_the_list_of_votes_keeps_out_what_never_came_to_a_vote(
    store: GraphStore,
) -> None:
    """``/api/decisions`` lists the decisions with an outcome, and its facets count those;
    ``unvoted=true`` also the others (withdrawn, postponed, held, lapsed)."""
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        votes = client.get("/api/decisions").json()
        assert votes["total"] == 1
        assert [i["decision_kind"] for i in votes["items"]] == ["Stemmen - verworpen"]
        assert votes["facets"]["passed"] == [{"value": False, "count": 1}]
        assert sum(k["count"] for k in votes["facets"]["kind"]) == 1

        every = client.get("/api/decisions?unvoted=true").json()
        assert every["total"] == 2
        assert {i["decision_kind"] for i in every["items"]} == {
            "Stemmen - verworpen",
            "Stemmen - ingetrokken",
        }
        assert {(p["value"], p["count"]) for p in every["facets"]["passed"]} == {
            (False, 1),
            (None, 1),
        }
        # the outcome filter still reads the outcome
        assert (
            client.get("/api/decisions?unvoted=true&passed=false").json()["total"] == 1
        )
    finally:
        app.dependency_overrides.pop(get_store, None)

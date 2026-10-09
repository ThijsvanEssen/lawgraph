"""A withdrawn amendment on a real database: its Besluit ``Stemmen - ingetrokken``, which no
Stemming carries (``fetch_bill_decisions(without_votes=True)``), is a decision on its case
without an outcome, and its case says the Kamer is done with it (``Zaak.Afgedaan``). An
amendment still open says so too. The records have the fields the API sends."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

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


WITHDRAWN, OPEN = _zaak(60, True), _zaak(61, False)


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


WITHDRAWAL = {
    "Id": uid(NUMBER, 7),
    "BesluitSoort": "Stemmen - ingetrokken",
    "BesluitTekst": "Ingetrokken.",
    "AgendapuntZaakBesluitVolgorde": 1,
    "Verwijderd": False,
    "Zaak": [WITHDRAWN],
    "Agendapunt": {
        "Onderwerp": "Ingetrokken amendement",
        "Activiteit": {"Soort": "Stemmingen", "Datum": "2024-04-25T15:00:00"},
        "Zaak": [WITHDRAWN],
    },
}


@pytest.fixture()
def store(database: str, cli: Any) -> Iterator[GraphStore]:
    store = GraphStore()
    records = [
        (RAW_KIND_TK_DOSSIER, DOSSIER),
        (RAW_KIND_TK_ZAAK, WITHDRAWN),
        (RAW_KIND_TK_ZAAK, OPEN),
        (RAW_KIND_TK_DOCUMENT, _paper(WITHDRAWN, 60)),
        (RAW_KIND_TK_DOCUMENT, _paper(OPEN, 61)),
        (RAW_KIND_TK_BESLUIT, WITHDRAWAL),
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
    }

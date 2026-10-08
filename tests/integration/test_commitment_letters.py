"""The letter that fulfils a commitment (``Toezegging.KamerbriefNakoming``): the real
``normalize tk-dossiers`` makes ``ANSWERS`` from the letter to the commitment, when the letter
is stored."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    RAW_KIND_TK_DOCUMENT,
    RAW_KIND_TK_TOEZEGGING,
    SOURCE_TK,
)
from lawgraph.db import GraphStore, RawSourceWriter, raw_source_doc
from tests.integration.seed import uid

COMMITMENT, LETTER, ABSENT = uid(1, 7), uid(2, 7), uid(3, 7)


def test_a_letter_answers_the_commitment_it_fulfils(database: str, cli: Any) -> None:
    store = GraphStore()
    records = [
        (
            RAW_KIND_TK_TOEZEGGING,
            {
                "Id": COMMITMENT,
                "Nummer": "TZ202603-130",
                "Tekst": "De minister stuurt de Kamer voor de zomer een brief.",
                "Naam": "Heinen, E.",
                "Functie": "Minister van Financiën",
                "Status": "Voldaan",
                "Aanmaakdatum": "2026-03-10T00:00:00+01:00",
                # the letter stored, and one that is not
                "KamerbriefNakoming": [{"Id": LETTER}, {"Id": ABSENT}],
            },
        ),
        (
            RAW_KIND_TK_DOCUMENT,
            {
                "Id": LETTER,
                "DocumentNummer": "2026D30000",
                "Soort": "Brief regering",
                "Onderwerp": "Brief over de toezegging",
                "Datum": "2026-06-30T00:00:00+02:00",
                "Volgnummer": -1,
            },
        ),
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
    cli("normalize", "tk-dossiers")

    answers = {
        (row["from_id"], row["to_id"])
        for row in store.query(
            "SELECT from_id, to_id FROM edges WHERE relation = 'ANSWERS'"
            " AND to_collection = 'commitments'"
        )
    }
    key = lambda guid: guid.lower().replace("-", "_")  # noqa: E731
    assert answers == {(f"documents/{key(LETTER)}", f"commitments/{key(COMMITMENT)}")}

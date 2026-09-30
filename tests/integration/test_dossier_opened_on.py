"""When a dossier opened: the date of nr. 1 of its own numbering, on a real database.

37500 is a bill whose Koninklijke boodschap (nr. 1, 25 June 2025) opens it. A letter that is
nr. 7 of another dossier (36000) is on the bill's case too, so it is part of 37500 as well,
and is older (1 January 2025): it does not open 37500.
"""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    RAW_KIND_TK_DOCUMENT,
    RAW_KIND_TK_DOSSIER,
    SOURCE_TK,
)
from lawgraph.db import ArangoStore, RawSourceWriter, raw_source_doc
from tests.integration.seed import uid

BILL, OTHER = 37500, 36000


def _dossier(number: int) -> dict[str, Any]:
    return {
        "Id": uid(number, 3),
        "Titel": f"Dossier {number}",
        "Nummer": number,
        "Toevoeging": None,
        "Afgesloten": False,
        "Kamer": "Tweede Kamer",
        "Verwijderd": False,
    }


def _paper(
    salt: int, kind: str, date: str, own: int, sequence: int, case: dict[str, Any]
) -> dict[str, Any]:
    return {
        "Id": uid(own * 10 + salt, 5),
        "Soort": kind,
        "Titel": f"Dossier {own}",
        "Onderwerp": kind,
        "Datum": f"{date}T00:00:00+02:00",
        "Volgnummer": sequence,
        "Zaak": [case],
        "Kamerstukdossier": [{"Id": uid(own, 3), "Nummer": own, "Toevoeging": None}],
        "DocumentActor": [],
    }


def test_nr_1_opens_the_dossier_not_an_older_paper_of_another(
    database: str, cli: Any
) -> None:
    store = ArangoStore()
    case = {
        "Id": uid(BILL, 2),
        "Soort": "Wetgeving",
        "Nummer": "2025Z37500",
        "Onderwerp": "Wetgeving",
        "Kamerstukdossier": [{"Id": uid(BILL, 3), "Nummer": BILL}],
    }
    records = [
        (RAW_KIND_TK_DOSSIER, _dossier(BILL)),
        (RAW_KIND_TK_DOSSIER, _dossier(OTHER)),
        (
            RAW_KIND_TK_DOCUMENT,
            _paper(1, "Koninklijke boodschap", "2025-06-25", BILL, 1, case),
        ),
        (
            RAW_KIND_TK_DOCUMENT,
            _paper(2, "Voorstel van wet", "2025-06-25", BILL, 2, case),
        ),
        (
            RAW_KIND_TK_DOCUMENT,
            _paper(3, "Brief regering", "2025-01-01", OTHER, 7, case),
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

    props = store.db.collection("dossiers").get(str(BILL))["props"]
    assert (props["opened_on"], props["opened_on_basis"]) == (
        "2025-06-25",
        "first_paper",
    )

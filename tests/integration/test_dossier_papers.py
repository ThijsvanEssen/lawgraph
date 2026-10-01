"""The papers of a dossier: each numbered in its own dossier, and the ones it lacks fetched.

A Document of the Tweede Kamer reaches every dossier of its cases (Zaak → Kamerstukdossier),
but it is a Kamerstuk of one dossier only (``Document.Kamerstukdossier``): a report of a
legislative consultation on five bills is nr. 11 of one of them. A nader rapport sent along
with a bill is part of its case and a Kamerstuk of no dossier (``Volgnummer`` -1).
"""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    RAW_KIND_TK_DOCUMENT,
    RAW_KIND_TK_DOSSIER,
    RAW_KIND_TK_ZAAK,
    SOURCE_TK,
)
from lawgraph.core.models import make_node_key
from lawgraph.db import ArangoStore, RawSourceWriter, raw_source_doc
from lawgraph.pipelines.retrieve import _gaps
from lawgraph.pipelines.retrieve.tk_content import DEFAULT_KINDS
from lawgraph.pipelines.retrieve.tk_dossiers import TKDossiersRetrievePipeline
from tests.integration.seed import uid

TITLE_31746 = "Wijziging van boek 2 van het Burgerlijk Wetboek (aandeelhoudersrechten)"
TITLE_31058 = "Wet vereenvoudiging en flexibilisering bv-recht"
DOSSIER_31746 = {"Id": uid(1, 3), "Nummer": 31746, "Toevoeging": None}
DOSSIER_31058 = {"Id": uid(2, 3), "Nummer": 31058, "Toevoeging": None}
# A dossier the cases name and the graph does not hold.
DOSSIER_36996 = {"Id": uid(3, 3), "Nummer": 36996, "Toevoeging": None}

BILL_31746 = {
    "Id": uid(1, 2),
    "Nummer": "2008Z04657",
    "Soort": "Wetgeving",
    "Titel": TITLE_31746,
    "Kamerstukdossier": [DOSSIER_31746],
}
BILL_31058 = {
    "Id": uid(2, 2),
    "Nummer": "2007Z01033",
    "Soort": "Wetgeving",
    "Titel": TITLE_31058,
    "Kamerstukdossier": [DOSSIER_31058],
}
LETTER_36996 = {
    "Id": uid(3, 2),
    "Nummer": "2026Z00003",
    "Soort": "Brief regering",
    "Titel": "Een brief",
    "Kamerstukdossier": [DOSSIER_36996],
}


def _paper(
    number: int,
    kind: str,
    sequence: int,
    cases: list[dict[str, Any]],
    dossier: dict[str, Any] | None,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "Id": uid(number, 1),
        "DocumentNummer": f"2009D{number:05d}",
        "Soort": kind,
        "Titel": TITLE_31746,
        "Onderwerp": kind,
        "Datum": "2009-10-26T00:00:00+01:00",
        "Volgnummer": sequence,
        "Verwijderd": False,
        "Zaak": cases,
        "Kamerstukdossier": [dossier] if dossier else [],
        "DocumentActor": [],
        **extra,
    }


MESSAGE = _paper(1, "Koninklijke boodschap", 1, [BILL_31746], DOSSIER_31746)
NADER_RAPPORT = _paper(2, "Nader rapport", -1, [BILL_31746], None)
AMENDMENT = _paper(
    3,
    "Amendement",
    11,
    [BILL_31746],
    DOSSIER_31746,
    Onderwerp="Amendement van het lid Irrgang over de registratietermijn",
)
WGO_REPORT = _paper(
    4,
    "Verslag van een wetgevingsoverleg",
    11,
    [BILL_31746, BILL_31058],
    DOSSIER_31058,
    Titel=TITLE_31058,
    Onderwerp="Verslag van een wetgevingsoverleg over wetsvoorstellen op het terrein "
    "van vennootschapsrecht",
)
AMENDMENTS_NOTE = _paper(5, "Nota van wijziging", 8, [BILL_31746], DOSSIER_31746)
LETTER = _paper(6, "Brief regering", 1, [LETTER_36996], DOSSIER_36996)


def _write(store: ArangoStore, records: list[tuple[str, dict[str, Any]]]) -> None:
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


def _load(store: ArangoStore, cli: Any) -> None:
    _write(
        store,
        [
            (RAW_KIND_TK_DOSSIER, {**DOSSIER_31746, "Titel": TITLE_31746}),
            (RAW_KIND_TK_DOSSIER, {**DOSSIER_31058, "Titel": TITLE_31058}),
            (RAW_KIND_TK_ZAAK, BILL_31746),
            (RAW_KIND_TK_ZAAK, BILL_31058),
            (RAW_KIND_TK_ZAAK, LETTER_36996),
            *(
                (RAW_KIND_TK_DOCUMENT, paper)
                for paper in (
                    MESSAGE,
                    NADER_RAPPORT,
                    AMENDMENT,
                    WGO_REPORT,
                    AMENDMENTS_NOTE,
                    LETTER,
                )
            ),
        ],
    )
    cli("normalize", "tk")
    cli("normalize", "tk-dossiers")


def test_a_paper_is_numbered_in_its_own_dossier(database: str, cli: Any) -> None:
    """31746 nr. 11 is the amendement; the report beside it is 31058 nr. 11, and the nader
    rapport is no Kamerstuk at all."""
    store = ArangoStore()
    _load(store, cli)

    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        listed = client.get("/api/dossiers/31746/documents").json()["items"]
        by_key = {item["key"]: item for item in listed}
        amendment = by_key[make_node_key(AMENDMENT["Id"])]
        report = by_key[make_node_key(WGO_REPORT["Id"])]
        nader = by_key[make_node_key(NADER_RAPPORT["Id"])]
        assert (amendment["dossier_number"], amendment["sequence"]) == ("31746", 11)
        assert (report["dossier_number"], report["sequence"]) == ("31058", 11)
        assert (nader["dossier_number"], nader["sequence"]) == (None, None)

        assert report["display_name"].startswith("Kamerstuk 31058, nr. 11")
        assert not nader["display_name"].startswith("Kamerstuk")

        # "31746, nr. 11" is the amendement, not the report that shares the number.
        resolved = client.get("/api/resolve", params={"q": "31746-11"}).json()
        assert resolved["match"]["key"] == make_node_key(AMENDMENT["Id"])
        assert resolved["alternatives"] == []
    finally:
        app.dependency_overrides.pop(get_store, None)

    # The XML of a paper is asked for at its own address, a nota van wijziging among them.
    wanted = {p["identifier"] for p in _gaps.kamerstuk_gaps(store, DEFAULT_KINDS)}
    assert wanted == {"kst-31746-11", "kst-31746-8"}


class _Kamer:
    """The Tweede Kamer: 31746 as it has it (nr. 2 to 10 are not in it either), 31058 with
    nr. 1 to 11, and no dossier 36996."""

    def __init__(self) -> None:
        self.asked: list[int] = []

    def fetch_dossiers(self, since: Any = None, number: int | None = None) -> Any:
        self.asked.append(int(number or 0))
        found = {31746: DOSSIER_31746, 31058: DOSSIER_31058}.get(int(number or 0))
        return iter([found] if found else [])

    def fetch_documents(
        self, since: Any = None, dossier_number: int | None = None
    ) -> Any:
        if dossier_number == 31058:
            return iter(
                [
                    _paper(100 + n, "Brief", n, [BILL_31058], DOSSIER_31058)
                    for n in range(1, 11)
                ]
                + [WGO_REPORT]
            )
        if dossier_number == 31746:
            return iter(
                [MESSAGE, NADER_RAPPORT, AMENDMENTS_NOTE, AMENDMENT, WGO_REPORT]
            )
        return iter([])


def test_the_gaps_are_the_missing_papers_and_the_dossiers_named(
    database: str, cli: Any
) -> None:
    """31746 lacks nr. 2 to 7 and 9 and 10, 31058 lacks nr. 1 to 10, and a letter names
    36996, which the graph does not hold: all three are fetched, per dossier. What the Kamer
    does not have either is not asked for again on the next run."""
    store = ArangoStore()
    _load(store, cli)

    assert _gaps.tk_dossier_gaps(store) == ["31058", "31746", "36996"]

    kamer = _Kamer()
    result = TKDossiersRetrievePipeline(store=store, client=kamer).run_gaps(  # type: ignore[arg-type]
        _gaps.tk_dossier_gaps(store)
    )
    assert result.errors == []
    assert kamer.asked == [31058, 31746, 36996]
    cli("normalize", "tk-dossiers")

    # 31058 is complete now; 31746 and 36996 are what the Kamer has.
    assert _gaps.tk_dossier_gaps(store) == []
    numbers = store.query(
        """SELECT props -> 'sequence' FROM documents
           WHERE lg_str(props -> 'dossier_number') = '31058'"""
    )
    assert sorted(numbers) == list(range(1, 12))

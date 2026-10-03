"""Whether a dossier is closed and how it ended, derived from the graph on a real database.

The Tweede Kamer record cannot say it: ``Kamerstukdossier`` has no ``Afgedaan`` and no
``DatumGesloten``, and ``Afgesloten`` is false on every dossier (34851, the Uitvoeringswet
AVG, law since Stb. 2018, 144, says false). The records below have the fields the API sends.

* 35786 changed the Grondwet: its article versions name it as the dossier of Stb. 2022, 332,
  so ``semantic bwb-amendments`` writes ``LEGISLATED_IN`` from that publication and it is
  enacted.
* 37014 (Wet weerbare waarden) is pending: an amendment on it was voted down, which does not
  end the bill.
* 36680 was withdrawn by letter: no record of the Kamer says so, so it stays open.
* 36999 was voted down by the Tweede Kamer.
* 36928 passed as a hamerstuk: a Besluit ``Stemmen - zonder stemming aannemen`` on its zaak
  without a single vote, fetched as a Besluit on a bill (``tk-besluit``); open, awaiting the
  Eerste Kamer, with the decision of the Kamer as ``tk_decision``.

The phases of a bill are what its papers and the decisions on it mark. The timeline marks
what came after the closing, and a meeting still planned.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    RAW_KIND_BWB_TOESTAND,
    RAW_KIND_BWB_TOESTAND_ALL,
    RAW_KIND_TK_ACTIVITEIT,
    RAW_KIND_TK_BESLUIT,
    RAW_KIND_TK_DOCUMENT,
    RAW_KIND_TK_DOSSIER,
    RAW_KIND_TK_STEMMING,
    SOURCE_BWB,
    SOURCE_TK,
)
from lawgraph.db import GraphStore, RawSourceWriter, raw_source_doc
from tests.integration.seed import FIXTURES, uid

GRONDWET = "BWBR0001840"
ENACTED, PENDING, WITHDRAWN, REJECTED = "35786", "37014", "36680", "36999"
HAMMERED = "36928"


def _dossier(number: str, title: str) -> dict[str, Any]:
    return {
        "Id": uid(int(number), 3),
        "Titel": title,
        "Citeertitel": None,
        "Alias": None,
        "Nummer": int(number),
        "Toevoeging": None,
        "HoogsteVolgnummer": 3,
        "Afgesloten": False,
        "Kamer": "Tweede Kamer",
        "GewijzigdOp": "2026-09-17T16:33:34.763+02:00",
        "ApiGewijzigdOp": "2026-09-17T14:33:39.6171021Z",
        "Verwijderd": False,
    }


def _zaak(number: str, salt: int, kind: str) -> dict[str, Any]:
    return {
        "Id": uid(int(number), salt),
        "Soort": kind,
        "Nummer": f"2025Z{number}{salt}",
        "Onderwerp": f"{kind} in dossier {number}",
        "Kamerstukdossier": [{"Id": uid(int(number), 3), "Nummer": int(number)}],
    }


def _document(
    number: str,
    salt: int,
    kind: str,
    subject: str,
    date: str,
    cases: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "Id": uid(int(number), salt),
        "Soort": kind,
        "Titel": f"Voorstel {number}",
        "Onderwerp": subject,
        "Datum": f"{date}T00:00:00+02:00",
        "Volgnummer": salt,
        "Zaak": cases,
        "DocumentActor": [],
    }


def _votes(
    number: str,
    salt: int,
    case: dict[str, Any],
    verdict: str,
    date: str,
    *,
    agenda: list[dict[str, Any]] | None = None,
    order: int = 1,
) -> Iterator[dict[str, Any]]:
    """The rows of one decision on *case*, one per faction, under an agenda item that holds
    *agenda* (only *case* when it is not given) as the TK API sends it."""
    decision = uid(int(number), salt)
    for faction, choice in ((1, "Voor"), (2, "Tegen")):
        yield {
            "Id": uid(int(number) * 10 + faction, salt),
            "Besluit_Id": decision,
            "Soort": choice,
            "FractieGrootte": 20,
            "ActorFractie": f"F{faction}",
            "Fractie_Id": uid(faction, 8),
            "Persoon_Id": None,
            "GewijzigdOp": "2026-09-23T09:00:00+02:00",
            "Besluit": {
                "Id": decision,
                "BesluitSoort": f"Stemmen - {verdict}",
                "BesluitTekst": f"{verdict.capitalize()}.",
                "AgendapuntZaakBesluitVolgorde": order,
                "Zaak": [case],
                "Agendapunt": {
                    "Onderwerp": case["Onderwerp"],
                    "Activiteit": {"Soort": "Stemmingen", "Datum": f"{date}T15:00:00"},
                    "Zaak": agenda or [case],
                },
            },
        }


def _hamerstuk(number: str, case: dict[str, Any]) -> dict[str, Any]:
    """A Besluit on the bill without votes, as ``fetch_bill_decisions`` expands it."""
    return {
        "Id": uid(int(number), 7),
        "BesluitSoort": "Stemmen - zonder stemming aannemen",
        "BesluitTekst": "Wetsvoorstel zonder stemming aangenomen.",
        "AgendapuntZaakBesluitVolgorde": 1,
        "Verwijderd": False,
        "Zaak": [case],
        "Agendapunt": {
            "Onderwerp": case["Onderwerp"],
            "Activiteit": {"Soort": "Hamerstukken", "Datum": "2026-06-25T10:15:00"},
            "Zaak": [case],
        },
    }


def _planned_meeting(number: str, case: dict[str, Any]) -> dict[str, Any]:
    """A procedure meeting on the dossier, announced after it closed and never held."""
    return {
        "Id": uid(int(number), 9),
        "Nummer": f"2025A{number}",
        "Soort": "Procedurevergadering",
        "Status": "Gepland",
        "Onderwerp": f"Procedurevergadering over {number}",
        "Datum": "2025-01-15T10:00:00+01:00",
        "Agendapunt": [{"Zaak": [case]}],
    }


def _tk_payloads() -> Iterator[tuple[str, dict[str, Any]]]:
    titles = {
        ENACTED: "Wijziging van de Grondwet (algemene bepaling)",
        PENDING: "Voorstel van wet van de leden Keijzer en Schilder (Wet weerbare waarden)",
        WITHDRAWN: "Wijziging van de Wet kinderopvang",
        REJECTED: "Wijziging van de Wegenwet",
        HAMMERED: "Wijziging van de Wet op de rechterlijke organisatie",
    }
    for number, title in titles.items():
        yield RAW_KIND_TK_DOSSIER, _dossier(number, title)
        bill = _zaak(
            number, 2, "Initiatiefwetgeving" if number == PENDING else "Wetgeving"
        )
        yield (
            RAW_KIND_TK_DOCUMENT,
            _document(number, 1, "Voorstel van wet", title, "2024-01-10", [bill]),
        )
        if number == PENDING:
            # The amendment is second on the agenda item, after the bill: its place in
            # that list is not what AgendapuntZaakBesluitVolgorde says.
            amendment = _zaak(number, 4, "Amendement")
            yield from (
                (RAW_KIND_TK_STEMMING, row)
                for row in _votes(
                    number,
                    7,
                    amendment,
                    "verworpen",
                    "2025-11-04",
                    agenda=[bill, amendment],
                    order=1,
                )
            )
        if number == ENACTED:
            yield (
                RAW_KIND_TK_DOCUMENT,
                _document(number, 5, "Eindtekst", title, "2022-06-01", [bill]),
            )
            yield RAW_KIND_TK_ACTIVITEIT, _planned_meeting(number, bill)
        if number == WITHDRAWN:
            letter = _zaak(number, 5, "Brief regering")
            yield (
                RAW_KIND_TK_DOCUMENT,
                _document(
                    number,
                    6,
                    "Brief regering",
                    "Brief houdende intrekking van het wetsvoorstel",
                    "2025-06-02",
                    [bill, letter],
                ),
            )
        if number == REJECTED:
            yield from (
                (RAW_KIND_TK_STEMMING, row)
                for row in _votes(number, 7, bill, "verworpen", "2025-03-11")
            )
        if number == HAMMERED:
            yield RAW_KIND_TK_BESLUIT, _hamerstuk(number, bill)


@pytest.fixture()
def store(database: str, cli: Any) -> Iterator[GraphStore]:
    store = GraphStore()
    with RawSourceWriter(store) as writer:
        for kind, payload in _tk_payloads():
            writer.add(
                raw_source_doc(
                    source=SOURCE_TK,
                    kind=kind,
                    external_id=payload["Id"],
                    payload_json=payload,
                )
            )
        for kind, external_id in (
            (RAW_KIND_BWB_TOESTAND, GRONDWET),
            (RAW_KIND_BWB_TOESTAND_ALL, f"{GRONDWET}@2023-02-22"),
        ):
            writer.add(
                raw_source_doc(
                    source=SOURCE_BWB,
                    kind=kind,
                    external_id=external_id,
                    payload_text=(FIXTURES / "bwb_grondwet_toestand.xml").read_text(),
                    meta={
                        "bwb_id": GRONDWET,
                        "state_url": f"https://repo/{GRONDWET}/x.xml",
                        "start_date": "2023-02-22",
                        "end_date": "9999-12-31",
                    },
                )
            )
    cli("normalize", "bwb")
    cli("normalize", "bwb-history")
    cli("normalize", "tk-dossiers")
    cli("semantic", "bwb-amendments")
    cli("semantic", "tk-dossier-outcomes")
    yield store


def _dossier_props(store: GraphStore) -> dict[str, dict[str, Any]]:
    kept = (
        "number", "closed", "outcome", "closed_on", "opened_on", "kind", "kind_basis",
        "phases", "current_phase", "tk_decision",
    )  # fmt: skip
    return {
        props["number"]: {k: v for k, v in props.items() if k in kept}
        for props in store.query("SELECT props FROM dossiers")
    }


def _done(props: dict[str, Any]) -> list[str]:
    return [p["name"] for p in props.get("phases") or [] if p["done"]]


def _outcome(props: dict[str, Any]) -> tuple[Any, ...]:
    return props.get("closed"), props.get("outcome"), props.get("closed_on")


def test_a_dossier_is_closed_by_what_the_graph_holds(
    store: GraphStore, cli: Any
) -> None:
    dossiers = _dossier_props(store)

    # Stb. 2022, 332 was published on 30 August 2022.
    assert _outcome(dossiers[ENACTED]) == (True, "aangenomen", "2022-08-30")
    assert _done(dossiers[ENACTED]) == ["Voorstel van wet", "Eindtekst"]
    assert _outcome(dossiers[REJECTED]) == (True, "verworpen", "2025-03-11")
    assert _done(dossiers[REJECTED]) == ["Voorstel van wet", "Stemmingen"]
    assert dossiers[REJECTED]["current_phase"] == "Stemmingen"
    assert dossiers[REJECTED]["tk_decision"] == {
        "kind": "Stemmen - verworpen",
        "text": "Verworpen.",
        "date": "2025-03-11",
    }
    # A withdrawal is read from nothing: the Kamer records none.
    assert _outcome(dossiers[WITHDRAWN]) == (False, None, None)
    # A rejected amendment is not the end of the bill, and no vote on the bill itself.
    assert _outcome(dossiers[PENDING]) == (False, None, None)
    assert (dossiers[PENDING]["kind"], dossiers[PENDING]["kind_basis"]) == (
        "Initiatiefwetgeving",
        "case",
    )
    assert _done(dossiers[PENDING]) == ["Voorstel van wet"]
    assert dossiers[PENDING]["tk_decision"] is None
    # A hamerstuk: adopted by the Tweede Kamer without votes, open for the Eerste Kamer.
    assert _outcome(dossiers[HAMMERED]) == (False, None, None)
    assert dossiers[HAMMERED]["tk_decision"] == {
        "kind": "Stemmen - zonder stemming aannemen",
        "text": "Wetsvoorstel zonder stemming aangenomen.",
        "date": "2026-06-25",
    }
    assert dossiers[HAMMERED]["current_phase"] == "Stemmingen"
    # Opened on its first document, which the record does not say either.
    assert dossiers[PENDING]["opened_on"] == "2024-01-10"

    # A new run of the records does not undo what was derived, and the step again
    # changes nothing.
    cli("normalize", "tk-dossiers")
    again = _dossier_props(store)
    assert again == dossiers
    done = cli("semantic", "tk-dossier-outcomes")
    assert "0 changed" in done.stderr + done.stdout


def test_the_api_lists_the_dossiers_that_did_not_end_as_open(
    store: GraphStore,
) -> None:
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        open_page = client.get("/api/dossiers?status=open").json()
        assert {item["number"] for item in open_page["items"]} == {
            PENDING,
            WITHDRAWN,
            HAMMERED,
        }
        hammered = client.get(f"/api/dossiers/{HAMMERED}").json()
        assert hammered["tk_decision"]["kind"] == "Stemmen - zonder stemming aannemen"
        assert hammered["current_phase"] == "Stemmingen"

        enacted = client.get(f"/api/dossiers/{ENACTED}").json()
        assert (enacted["closed"], enacted["outcome"], enacted["closed_on"]) == (
            True,
            "aangenomen",
            "2022-08-30",
        )
        pending = client.get(f"/api/dossiers/{PENDING}").json()
        assert (pending["closed"], pending["outcome"]) == (False, None)
    finally:
        app.dependency_overrides.pop(get_store, None)


def test_the_api_types_the_kind_of_case_a_vote_and_a_paper_belong_to(
    store: GraphStore,
) -> None:
    """A vote on the bill itself says ``Wetgeving``, one on an amendment ``Amendement``;
    a letter carries the kinds of its cases."""
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)

        def decision_kind(number: str) -> tuple[Any, Any]:
            key = client.get("/api/decisions", params={"dossier": number}).json()
            detail = client.get(f"/api/decisions/{key['items'][0]['key']}").json()
            timeline = client.get(f"/api/dossiers/{number}/timeline").json()
            vote = next(e for e in timeline["entries"] if e["node_type"] == "decision")
            return detail["primary_case_kind"], vote["body"]["primary_case_kind"]

        assert decision_kind(REJECTED) == ("Wetgeving", "Wetgeving")
        assert decision_kind(PENDING) == ("Amendement", "Amendement")

        documents = client.get(f"/api/dossiers/{WITHDRAWN}/documents").json()["items"]
        letters = [d for d in documents if d["kind"] == "Brief regering"]
        letter = client.get(f"/api/documents/{letters[0]['key']}").json()
        assert letter["dossier_numbers"] == [WITHDRAWN]
        assert letter["case_kinds"] == ["Wetgeving", "Brief regering"]
    finally:
        app.dependency_overrides.pop(get_store, None)


def test_the_timeline_marks_what_came_after_the_closing(store: GraphStore) -> None:
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        url = f"/api/dossiers/{ENACTED}/timeline"
        entries = client.get(url, params={"order": "asc"}).json()["entries"]
        marks = [
            (e["kind"], e["date"][:10], e["after_closure"], e["planned"])
            for e in entries
        ]
        # Closed on 2022-08-30, the day Stb. 2022, 332 was published.
        assert marks == [
            ("Eindtekst", "2022-06-01", False, False),
            ("Voorstel van wet", "2024-01-10", True, False),
            ("Procedurevergadering", "2025-01-15", True, True),
        ]
        held = client.get(url, params={"include_planned": "false"}).json()
        assert [e["kind"] for e in held["entries"]] == [
            "Voorstel van wet",
            "Eindtekst",
        ]
        detail = client.get(f"/api/dossiers/{ENACTED}").json()
        # the furthest phase done, not the latest date: its voorstel is dated after its
        # Eindtekst
        assert (detail["kind"], detail["current_phase"]) == ("Wetgeving", "Eindtekst")

        pending = client.get(f"/api/dossiers/{PENDING}/timeline").json()["entries"]
        assert pending and not any(e["after_closure"] for e in pending)
    finally:
        app.dependency_overrides.pop(get_store, None)

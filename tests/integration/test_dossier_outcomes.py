"""Whether a dossier is closed and how it ended, derived from the graph on a real database.

The Tweede Kamer record cannot say it: ``Kamerstukdossier`` has no ``Afgedaan`` and no
``DatumGesloten``, and ``Afgesloten`` is false on every dossier (34851, the Uitvoeringswet
AVG, law since Stb. 2018, 144, says false). The records below have the fields the API sends.

* 35786 changed the Grondwet: the toestand of the Grondwet names it as the dossier of
  Stb. 2022, 332, so ``semantic bwb-amendments`` writes ``LEGISLATED_IN`` and it is enacted.
* 37014 (Wet weerbare waarden) is pending: an amendment on it was voted down, which does not
  end the bill.
* 36680 was withdrawn by letter; 36999 was voted down by the Tweede Kamer.

Closing a dossier recomputes its stages: while open, 35786 showed only its bill and missed
nothing; closed, it passed every stage a bill passes, and only its adopted text (``Eindtekst``)
shows the vote. Its timeline marks what came after the closing, and a meeting still planned.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    RAW_KIND_BWB_TOESTAND,
    RAW_KIND_TK_ACTIVITEIT,
    RAW_KIND_TK_DOCUMENT,
    RAW_KIND_TK_DOSSIER,
    RAW_KIND_TK_STEMMING,
    SOURCE_BWB,
    SOURCE_TK,
)
from lawgraph.db import ArangoStore, RawSourceWriter, raw_source_doc
from lawgraph.db.queries.dossiers import get_recent_dossiers
from tests.integration.seed import FIXTURES, uid

GRONDWET = "BWBR0001840"
ENACTED, PENDING, WITHDRAWN, REJECTED = "35786", "37014", "36680", "36999"


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


@pytest.fixture()
def store(database: str, cli: Any) -> Iterator[ArangoStore]:
    store = ArangoStore()
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
        writer.add(
            raw_source_doc(
                source=SOURCE_BWB,
                kind=RAW_KIND_BWB_TOESTAND,
                external_id=GRONDWET,
                payload_text=(FIXTURES / "bwb_grondwet_toestand.xml").read_text(),
                meta={
                    "bwb_id": GRONDWET,
                    "state_url": f"https://repo/{GRONDWET}/x.xml",
                },
            )
        )
    cli("normalize", "bwb")
    cli("normalize", "tk-dossiers")
    cli("semantic", "bwb-amendments")
    cli("semantic", "tk-dossier-outcomes")
    yield store


def _dossier_props(store: ArangoStore) -> dict[str, dict[str, Any]]:
    return {
        row["number"]: row
        for row in store.query(
            "FOR d IN dossiers RETURN MERGE(KEEP(d.props, 'number', 'closed', 'outcome', "
            "'closed_on', 'opened_on', 'current_stage', 'stages_present', "
            "'stages_complete', 'stages_missing'), {})"
        )
    }


def _outcome(props: dict[str, Any]) -> tuple[Any, ...]:
    return props.get("closed"), props.get("outcome"), props.get("closed_on")


def test_a_dossier_is_closed_by_what_the_graph_holds(
    store: ArangoStore, cli: Any
) -> None:
    dossiers = _dossier_props(store)

    # Stb. 2022, 332 was published on 30 August 2022.
    assert _outcome(dossiers[ENACTED]) == (True, "aangenomen", "2022-08-30")
    assert dossiers[ENACTED]["current_stage"] == "afgehandeld"
    assert dossiers[ENACTED]["stages_present"][-1] == "afgehandeld"
    # Closed, it passed the memorandum and the advice, which the graph lacks; its
    # adopted text shows the vote. Open, it missed nothing: the step recomputed it.
    assert dossiers[ENACTED]["stages_complete"] is False
    assert dossiers[ENACTED]["stages_missing"] == ["mvt", "advies_rvs"]
    assert dossiers[REJECTED]["stages_missing"] == ["mvt", "advies_rvs"]
    assert dossiers[WITHDRAWN]["stages_missing"] == ["mvt", "advies_rvs"]
    # Open, at the vote on its amendment.
    assert dossiers[PENDING]["current_stage"] == "stemming"
    assert dossiers[PENDING]["stages_missing"] == ["mvt", "advies_rvs"]
    assert _outcome(dossiers[WITHDRAWN]) == (True, "ingetrokken", "2025-06-02")
    assert _outcome(dossiers[REJECTED]) == (True, "verworpen", "2025-03-11")
    # A rejected amendment is not the end of the bill.
    assert _outcome(dossiers[PENDING]) == (False, None, None)
    assert dossiers[PENDING]["current_stage"] != "afgehandeld"
    # Opened on its first document, which the record does not say either.
    assert dossiers[PENDING]["opened_on"] == "2024-01-10"

    # A new run of the records does not undo what was derived, and the step again
    # changes nothing.
    cli("normalize", "tk-dossiers")
    again = _dossier_props(store)
    assert again == dossiers
    done = cli("semantic", "tk-dossier-outcomes")
    assert "0 changed" in done.stderr + done.stdout


def test_the_api_lists_only_the_pending_dossier_as_open(store: ArangoStore) -> None:
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        open_page = client.get("/api/dossiers/open").json()
        assert [item["number"] for item in open_page["items"]] == [PENDING]
        assert open_page["total"] == 1

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
    store: ArangoStore,
) -> None:
    """A vote on the bill itself says ``Wetgeving``, one on an amendment ``Amendement``;
    the withdrawal letter carries the kinds of its cases."""
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

        letters = client.get(
            "/api/documents", params={"dossier": WITHDRAWN, "kind": "Brief regering"}
        ).json()["items"]
        assert letters[0]["dossier_numbers"] == [WITHDRAWN]
        letter = client.get(f"/api/documents/{letters[0]['key']}").json()
        assert letter["case_kinds"] == ["Wetgeving", "Brief regering"]
    finally:
        app.dependency_overrides.pop(get_store, None)


def test_recent_dossiers_include_one_that_closed_without_an_activity(
    store: ArangoStore,
) -> None:
    """A law is published in the Staatsblad, not in a debate: the dossier that closed
    by it is recent, and comes before the ones with older evidence."""
    today = dt.date.today().isoformat()
    store.db.collection("dossiers").update(
        {"_key": ENACTED, "props": {"closed_on": today}}
    )
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        recent = client.get("/api/dossiers/recent", params={"days": 30}).json()
        assert [(d["number"], d["closed"], d["outcome"]) for d in recent] == [
            (ENACTED, True, "aangenomen")
        ]
    finally:
        app.dependency_overrides.pop(get_store, None)

    # Over a longer window the most recent evidence comes first.
    longer = get_recent_dossiers(store, days=5000)
    assert [d["props"]["label"] for d in longer] == [
        ENACTED,  # closed today
        PENDING,  # the vote on its amendment, 2025-11-04
        WITHDRAWN,  # the letter, 2025-06-02
        REJECTED,  # the vote, 2025-03-11
    ]


def test_the_timeline_marks_what_came_after_the_closing(store: ArangoStore) -> None:
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
        assert (detail["stages_complete"], detail["stages_missing"]) == (
            False,
            ["mvt", "advies_rvs"],
        )

        pending = client.get(f"/api/dossiers/{PENDING}/timeline").json()["entries"]
        assert pending and not any(e["after_closure"] for e in pending)
    finally:
        app.dependency_overrides.pop(get_store, None)

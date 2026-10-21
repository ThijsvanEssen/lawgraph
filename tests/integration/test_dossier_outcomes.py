"""Whether a dossier is closed and how it ended, derived from the graph on a real database.

The Tweede Kamer record cannot say it: ``Kamerstukdossier`` has no ``Afgedaan`` and no
``DatumGesloten``, and ``Afgesloten`` is false on every dossier (34851, the Uitvoeringswet
AVG, law since Stb. 2018, 144, says false). The records below have the fields the API sends.

* 35786 changed the Grondwet: its article versions name it as the dossier of Stb. 2022, 332,
  so ``semantic bwb-amendments`` writes ``LEGISLATED_IN`` from that publication and it is
  enacted.
* 37014 (Wet weerbare waarden) is pending: an amendment on it was voted down, which does not
  end the bill.
* 36680 was withdrawn by the letter 2025D25397 (Kamerstuk 36680, nr. 6), whose Onderwerp is
  the fixed title of such a letter, with the space the Kamer leaves after it: it is
  ``ingetrokken`` on the day of that letter.
* 37014 also has a letter whose Onderwerp is that title with more after it, as the Kamer
  gave 2013D07117 on 32538 ("… Kaderwet Veteranen "): no withdrawal letter.
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

from lawgraph.config.constants import (
    RAW_KIND_BWB_TOESTAND,
    RAW_KIND_BWB_TOESTAND_ALL,
    RAW_KIND_TK_ACTIVITEIT,
    RAW_KIND_TK_BESLUIT,
    RAW_KIND_TK_DOCUMENT,
    RAW_KIND_TK_DOSSIER,
    RAW_KIND_TK_STEMMING,
)
from lawgraph.core.models import make_node_key
from lawgraph.db import GraphStore
from tests.databases import Api, module_store
from tests.integration.seed import FIXTURES, uid, write_tk, write_toestanden

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
            # Not the fixed title: words follow it, so it withdraws nothing.
            letter = _zaak(number, 5, "Brief regering")
            yield (
                RAW_KIND_TK_DOCUMENT,
                _document(
                    number,
                    6,
                    "Brief regering",
                    "Brief houdende intrekking van het wetsvoorstel Kaderwet Veteranen ",
                    "2025-12-01",
                    [bill, letter],
                ),
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
                    "Brief houdende intrekking van het wetsvoorstel ",
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


# The tests read one database built for them all (``store``), on the worker that built it;
# the one that runs the pipelines again has a database of its own (``database``).
pytestmark = pytest.mark.xdist_group("dossier_outcomes")


def _build(store: GraphStore, cli: Any) -> None:
    write_tk(store, _tk_payloads())
    write_toestanden(
        store,
        [
            (
                kind,
                external_id,
                (FIXTURES / "bwb_grondwet_toestand.xml").read_text(),
                {
                    "bwb_id": GRONDWET,
                    "state_url": f"https://repo/{GRONDWET}/x.xml",
                    "start_date": "2023-02-22",
                    "end_date": "9999-12-31",
                },
            )
            for kind, external_id in (
                (RAW_KIND_BWB_TOESTAND, GRONDWET),
                (RAW_KIND_BWB_TOESTAND_ALL, f"{GRONDWET}@2023-02-22"),
            )
        ],
    )
    cli("normalize", "bwb")
    cli("normalize", "bwb-history")
    cli("normalize", "tk-dossiers")
    cli("semantic", "bwb-amendments")
    cli("semantic", "tk-dossier-outcomes")


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Iterator[GraphStore]:
    """Built once for the tests that only read it."""
    with module_store(tmp_path_factory) as (store, cli):
        _build(store, cli)
        yield store


def _dossier_props(store: GraphStore) -> dict[str, dict[str, Any]]:
    kept = (
        "number", "closed", "outcome", "closed_on", "opened_on", "kind", "kind_basis",
        "phases", "current_phase", "tk_decision", "withdrawal_letter",
    )  # fmt: skip
    return {
        props["number"]: {k: v for k, v in props.items() if k in kept}
        for props in store.query("SELECT props FROM dossiers")
    }


def _done(props: dict[str, Any]) -> list[str]:
    return [p["name"] for p in props.get("phases") or [] if p["done"]]


def _outcome(props: dict[str, Any]) -> tuple[Any, ...]:
    return props.get("closed"), props.get("outcome"), props.get("closed_on")


def test_a_dossier_is_closed_by_what_the_graph_holds(database: str, cli: Any) -> None:
    store = GraphStore()
    _build(store, cli)
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
    # Withdrawn by the letter with the fixed title, on its day, with the letter as proof.
    assert _outcome(dossiers[WITHDRAWN]) == (True, "ingetrokken", "2025-06-02")
    letter = make_node_key(uid(int(WITHDRAWN), 6))
    assert dossiers[WITHDRAWN]["withdrawal_letter"] == f"documents/{letter}"
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
    api: Api,
) -> None:
    open_page = api.get_json("/api/dossiers?status=open")
    assert {item["number"] for item in open_page["items"]} == {PENDING, HAMMERED}
    hammered = api.get_json(f"/api/dossiers/{HAMMERED}")
    assert hammered["tk_decision"]["kind"] == "Stemmen - zonder stemming aannemen"
    assert hammered["current_phase"] == "Stemmingen"

    enacted = api.get_json(f"/api/dossiers/{ENACTED}")
    assert (enacted["closed"], enacted["outcome"], enacted["closed_on"]) == (
        True,
        "aangenomen",
        "2022-08-30",
    )
    pending = api.get_json(f"/api/dossiers/{PENDING}")
    assert (pending["closed"], pending["outcome"]) == (False, None)

    # What the graph knows of the end: the closing day of an ended bill, a withdrawn one
    # too; of an open one only that none is recorded since its last activity.
    def outcome(body: dict[str, Any]) -> dict[str, Any]:
        part = body["completeness"]["outcome"]
        return {k: v for k, v in part.items() if v is not None}

    assert outcome(enacted) == {"state": "done", "as_of": "2022-08-30"}
    assert outcome(pending) == {"state": "pending", "as_of": "2025-12-01"}
    withdrawn = api.get_json(f"/api/dossiers/{WITHDRAWN}")
    assert (withdrawn["closed"], withdrawn["outcome"], withdrawn["closed_on"]) == (
        True,
        "ingetrokken",
        "2025-06-02",
    )
    assert outcome(withdrawn) == {"state": "done", "as_of": "2025-06-02"}
    letter = api.get_json(f"/api/documents/{withdrawn['withdrawal_letter']}")
    assert (letter["kind"], letter["date"][:10]) == ("Brief regering", "2025-06-02")
    closed = api.get_json("/api/dossiers", status="closed", outcome="ingetrokken")
    assert [item["number"] for item in closed["items"]] == [WITHDRAWN]


def test_the_api_types_the_kind_of_case_a_vote_and_a_paper_belong_to(
    api: Api,
) -> None:
    """A vote on the bill itself says ``Wetgeving``, one on an amendment ``Amendement``;
    a letter carries the kinds of its cases."""

    def decided_case_kind(number: str) -> tuple[Any, Any]:
        key = api.get_json("/api/decisions", dossier=number)
        detail = api.get_json(f"/api/decisions/{key['items'][0]['key']}")
        timeline = api.get_json(f"/api/dossiers/{number}/timeline")
        vote = next(e for e in timeline["entries"] if e["node_type"] == "decision")
        return detail["primary_case_kind"], vote["body"]["primary_case_kind"]

    assert decided_case_kind(REJECTED) == ("Wetgeving", "Wetgeving")
    assert decided_case_kind(PENDING) == ("Amendement", "Amendement")

    documents = api.get_json(f"/api/dossiers/{WITHDRAWN}/documents")["items"]
    letters = [d for d in documents if d["kind"] == "Brief regering"]
    letter = api.get_json(f"/api/documents/{letters[0]['key']}")
    assert letter["dossier_numbers"] == [WITHDRAWN]
    assert letter["case_kinds"] == ["Wetgeving", "Brief regering"]


def test_the_timeline_marks_what_came_after_the_closing(api: Api) -> None:
    url = f"/api/dossiers/{ENACTED}/timeline"
    entries = api.get_json(url, order="asc")["entries"]
    marks = [
        (e["kind"], e["date"][:10], e["after_closure"], e["planned"]) for e in entries
    ]
    # Closed on 2022-08-30, the day Stb. 2022, 332 was published.
    assert marks == [
        ("Eindtekst", "2022-06-01", False, False),
        ("Voorstel van wet", "2024-01-10", True, False),
        ("Procedurevergadering", "2025-01-15", True, True),
    ]
    held = api.get_json(url, include_planned="false")
    assert [e["kind"] for e in held["entries"]] == [
        "Voorstel van wet",
        "Eindtekst",
    ]
    detail = api.get_json(f"/api/dossiers/{ENACTED}")
    # the furthest phase done, not the latest date: its voorstel is dated after its
    # Eindtekst
    assert (detail["kind"], detail["current_phase"]) == ("Wetgeving", "Eindtekst")

    pending = api.get_json(f"/api/dossiers/{PENDING}/timeline")["entries"]
    assert pending and not any(e["after_closure"] for e in pending)

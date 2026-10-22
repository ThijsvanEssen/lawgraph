"""A debate and what was made in it, from the real ``normalize tk``, ``normalize tk-dossiers``
and ``semantic tk-dossier-relations`` to the API.

The wetgevingsoverleg on the Cyberbeveiligingswet (36764) and the Wwke (36765) of 23 March
2026: its stenogram and verslag (``Document.Activiteit``), two motions submitted in it (their
cases on its agenda, started that day), a commitment made in it (registered on 10 April) and
fulfilled by letter nr. 33. The same day the Kamer voted on one of the motions in a
``Stemmingen`` that has its case on its agenda too: the motion was not submitted there.
A letter of another dossier answers the other motion (``Zaak.GerelateerdNaar``).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest

from lawgraph.config.constants import (
    RAW_KIND_TK_ACTIVITEIT,
    RAW_KIND_TK_COMMISSIE,
    RAW_KIND_TK_DOCUMENT,
    RAW_KIND_TK_DOSSIER,
    RAW_KIND_TK_STEMMING,
    RAW_KIND_TK_TOEZEGGING,
    RAW_KIND_TK_ZAAK,
)
from lawgraph.db import GraphStore
from lawgraph.db.queries import sitemaps
from tests.asserts import assert_status, show_items
from tests.databases import Api, module_store
from tests.integration.seed import uid, write_tk

DEBATE, VOTES = uid(1, 31), uid(2, 31)
BILL, MOTION_28, MOTION_23, LETTER_CASE = (uid(n, 32) for n in range(1, 5))
STENOGRAM, VERSLAG, DOCUMENT_28, DOCUMENT_23, LETTER_33, LETTER_12 = (
    uid(n, 33) for n in range(1, 7)
)
COMMITTEE, COMMITMENT, DECISION, VOTE = uid(1, 34), uid(2, 34), uid(3, 34), uid(4, 34)

DAY = "2026-03-23T10:00:00+01:00"
CBW = {"Nummer": 36764, "Toevoeging": None}
WWKE = {"Nummer": 36765, "Toevoeging": None}
OTHER = {"Nummer": 32761, "Toevoeging": None}


def _case(guid: str, number: str, kind: str, dossier: dict[str, Any], **extra: Any):
    return {
        "Id": guid,
        "Nummer": number,
        "Soort": kind,
        "Onderwerp": f"{kind} {number}",
        "GestartOp": DAY,
        "Kamerstukdossier": [dossier],
        **extra,
    }


CASES = {
    BILL: _case(BILL, "2025Z11344", "Wetgeving", CBW, GestartOp="2025-06-02"),
    MOTION_28: _case(MOTION_28, "2026Z05830", "Motie", CBW),
    MOTION_23: _case(MOTION_23, "2026Z05832", "Motie", CBW),
    LETTER_CASE: _case(
        LETTER_CASE,
        "2026Z20000",
        "Brief regering",
        OTHER,
        GestartOp="2026-07-01",
        GerelateerdNaar=[
            {"Id": MOTION_28, "Soort": "Motie", "Kamerstukdossier": [CBW]}
        ],
    ),
}


def _document(
    guid: str,
    kind: str,
    subject: str,
    sequence: int | None,
    *,
    case: str | None = None,
    dossier: dict[str, Any] | None = CBW,
    day: str = DAY,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "Id": guid,
        "DocumentNummer": f"2026D{int(guid[-4:], 16):05d}",
        "Soort": kind,
        "Onderwerp": subject,
        "Datum": day,
        "Volgnummer": sequence if sequence is not None else -1,
        "Zaak": [CASES[case]] if case else [],
        "Kamerstukdossier": [dossier] if dossier else [],
        **extra,
    }


def _records() -> list[tuple[str, dict[str, Any]]]:
    agenda = [CASES[BILL], CASES[MOTION_28], CASES[MOTION_23]]
    records: list[tuple[str, dict[str, Any]]] = [
        (RAW_KIND_TK_DOSSIER, {"Id": uid(n, 35), **d, "Titel": f"Dossier {n}"})
        for n, d in enumerate((CBW, WWKE, OTHER), start=1)
    ]
    records += [(RAW_KIND_TK_ZAAK, case) for case in CASES.values()]
    records.append(
        (
            RAW_KIND_TK_COMMISSIE,
            {"Id": COMMITTEE, "NaamNL": "Justitie en Veiligheid", "Afkorting": "JenV"},
        )
    )
    records += [
        (
            RAW_KIND_TK_ACTIVITEIT,
            {
                "Id": DEBATE,
                "Nummer": "2026A01323",
                "Soort": "Wetgevingsoverleg",
                "Onderwerp": "Wet weerbaarheid kritieke entiteiten (36765) en "
                "Cyberbeveiligingswet (36764)",
                "Status": "Uitgevoerd",
                "Datum": DAY,
                "Voortouwcommissie_Id": COMMITTEE,
                "Voortouwafkorting": "JenV",
                "Agendapunt": [
                    {"Zaak": agenda},
                    {"Zaak": [_case(uid(9, 32), "2025Z11356", "Wetgeving", WWKE)]},
                ],
            },
        ),
        (
            RAW_KIND_TK_ACTIVITEIT,
            {
                "Id": VOTES,
                "Nummer": "2026A01400",
                "Soort": "Stemmingen",
                "Onderwerp": "Stemmingen",
                "Status": "Uitgevoerd",
                "Datum": "2026-03-23T18:00:00+01:00",
                "Voortouwafkorting": "TK",
                "Agendapunt": [{"Zaak": [CASES[MOTION_23]]}],
            },
        ),
    ]
    records += [
        (
            RAW_KIND_TK_DOCUMENT,
            _document(
                STENOGRAM,
                "Stenogram",
                "Stenogram wetgevingsoverleg",
                None,
                dossier=None,
                Activiteit=[{"Id": DEBATE}],
            ),
        ),
        (
            RAW_KIND_TK_DOCUMENT,
            _document(
                VERSLAG,
                "Verslag van een wetgevingsoverleg",
                "Verslag van een wetgevingsoverleg",
                32,
                day="2026-04-20T00:00:00+02:00",
                Activiteit=[{"Id": DEBATE}],
            ),
        ),
        (
            RAW_KIND_TK_DOCUMENT,
            _document(
                DOCUMENT_28, "Motie", "Motie van het lid Kathmann", 28, case=MOTION_28
            ),
        ),
        (
            RAW_KIND_TK_DOCUMENT,
            _document(
                DOCUMENT_23,
                "Motie",
                "Motie van het lid Van den Berg",
                23,
                case=MOTION_23,
            ),
        ),
        (
            RAW_KIND_TK_DOCUMENT,
            _document(
                LETTER_33,
                "Brief regering",
                "Uitvoering van de aangenomen moties en toezeggingen",
                33,
                day="2026-06-24T00:00:00+02:00",
            ),
        ),
        (
            RAW_KIND_TK_DOCUMENT,
            _document(
                LETTER_12,
                "Brief regering",
                "Reactie op de motie Kathmann",
                12,
                case=LETTER_CASE,
                dossier=OTHER,
                day="2026-07-01T00:00:00+02:00",
            ),
        ),
        (
            RAW_KIND_TK_TOEZEGGING,
            {
                "Id": COMMITMENT,
                "Nummer": "TZ202604-064",
                "Tekst": "De minister van JenV zegt toe de samenwerkingsafspraken te delen.",
                "Naam": "Van Weel, D.M.",
                "Functie": "minister van Justitie en Veiligheid",
                "Status": "Afgedaan",
                "Aanmaakdatum": "2026-04-10T00:00:00+02:00",
                "ActiviteitNummer": "2026A01323",
                "Activiteit": [{"Datum": DAY}],
                "KamerbriefNakoming": [{"Id": LETTER_33}],
            },
        ),
        # the vote on motion 23, taken in the Stemmingen of the same day
        (
            RAW_KIND_TK_STEMMING,
            {
                "Id": VOTE,
                "Besluit_Id": DECISION,
                "Soort": "Voor",
                "FractieGrootte": 150,
                "ActorFractie": "Alle",
                "Fractie_Id": uid(1, 36),
                "Persoon_Id": None,
                "GewijzigdOp": "2026-03-23T18:30:00+01:00",
                "Besluit": {
                    "Id": DECISION,
                    "BesluitSoort": "Stemmen - aangenomen",
                    "BesluitTekst": "Aangenomen.",
                    "Zaak": [CASES[MOTION_23]],
                    "Agendapunt": {
                        "Onderwerp": "Stemmingen over moties",
                        "Activiteit": {"Id": VOTES, "Datum": DAY},
                    },
                },
            },
        ),
    ]
    return records


def _key(guid: str) -> str:
    return guid.lower().replace("-", "_")


# The tests read one database built for them all (``store``), on the worker that built it;
# the ones that write have a database of their own (``database``).
pytestmark = pytest.mark.xdist_group("debate")


def _build(store: GraphStore, cli: Any) -> None:
    write_tk(store, _records())
    cli("normalize", "tk")
    cli("normalize", "tk-dossiers")
    cli("semantic", "tk-dossier-relations")


@pytest.fixture(scope="module")
def store(tmp_path_factory: pytest.TempPathFactory) -> Iterator[GraphStore]:
    """Built once for the tests that only read it."""
    with module_store(tmp_path_factory) as (store, cli):
        _build(store, cli)
        yield store


def _made_in(store: GraphStore) -> set[tuple[str, str]]:
    return {
        (row["from_id"], row["to_id"])
        for row in store.query(
            "SELECT from_id, to_id FROM edges WHERE relation = 'MADE_IN'"
            " AND source = 'tk-dossier-relations'"
        )
    }


def test_a_motion_is_made_in_the_debate_it_was_submitted_in(
    database: str, cli: Any
) -> None:
    """Both motions in the debate; motion 23 not in the Stemmingen of the same day, which
    has its case on its agenda and took the decision on it."""
    store = GraphStore()
    _build(store, cli)
    expected = {
        (f"documents/{_key(DOCUMENT_28)}", f"activities/{_key(DEBATE)}"),
        (f"documents/{_key(DOCUMENT_23)}", f"activities/{_key(DEBATE)}"),
    }
    assert _made_in(store) == expected
    # a second run writes the same; an edge no longer derived goes
    cli("semantic", "tk-dossier-relations")
    assert _made_in(store) == expected
    store.execute(
        'UPDATE cases SET props = (props::jsonb || \'{"started_on": "2026-03-01"}\')'
        "::json WHERE id = %(id)s",
        {"id": f"cases/{_key(MOTION_23)}"},
    )
    cli("semantic", "tk-dossier-relations")
    assert _made_in(store) == {
        (f"documents/{_key(DOCUMENT_28)}", f"activities/{_key(DEBATE)}")
    }


def test_the_debate_has_its_head_and_its_records(api: Api) -> None:
    debate = api.get_json(f"/api/activities/{_key(DEBATE)}")
    assert debate["number"] == "2026A01323"
    assert debate["path"] == "/activiteiten/2026A01323"
    assert (debate["kind"], debate["date"], debate["status"]) == (
        "Wetgevingsoverleg",
        "2026-03-23",
        "Uitgevoerd",
    )
    assert debate["agenda_title"].startswith("Wet weerbaarheid kritieke entiteiten")
    assert debate["committee"]["name"] == "Justitie en Veiligheid"
    assert debate["committee"]["path"].startswith("/commissies/")
    # both dossiers, with their names
    assert sorted(debate["dossier_numbers"]) == ["36764", "36765"]
    assert {d["number"] for d in debate["dossiers"]} == {"36764", "36765"}
    assert debate["tk_url"].endswith("2026A01323")
    assert (debate["moved_from"], debate["moved_to"]) == ([], [])

    records = api.get_json(f"/api/activities/{_key(DEBATE)}/records")
    assert [(d["kind"], d["sequence"], d["path"]) for d in records["documents"]] == [
        ("Stenogram", None, None),
        ("Verslag van een wetgevingsoverleg", 32, "/kamerstukken/36764/32"),
    ]
    assert [(m["sequence"], m["path"]) for m in records["motions"]] == [
        (23, "/kamerstukken/36764/23"),
        (28, "/kamerstukken/36764/28"),
    ]
    (commitment,) = records["commitments"]
    assert (commitment["number"], commitment["registered_on"], commitment["path"]) == (
        "TZ202604-064",
        "2026-04-10",
        "/toezeggingen/TZ202604-064",
    )
    assert records["decisions"] == []
    # the case of the Wwke is on the agenda but not in the graph: its dossier is, by number
    assert {c["number"] for c in records["cases"]} == {
        "2025Z11344",
        "2026Z05830",
        "2026Z05832",
    }
    failing = [c for c in records["cases"] if c["path"] != f"/zaken/{c['number']}"]
    assert not failing, show_items(failing)

    votes = api.get_json(f"/api/activities/{_key(VOTES)}/records")
    assert (votes["motions"], votes["documents"]) == ([], [])
    (decision,) = votes["decisions"]
    assert decision["passed"] is True and decision["path"].startswith("/stemmingen/")

    assert_status(api.get("/api/activities/nothing"), 404)
    assert_status(api.get("/api/activities/nothing/records"), 404)


def test_the_debate_is_found_by_its_number(api: Api, store: GraphStore) -> None:
    found = api.get_json("/api/lookup", kind="activity", number="2026a01323")
    assert found["id"] == f"activities/{_key(DEBATE)}"
    assert found["path"] == "/activiteiten/2026A01323"
    assert_status(
        api.get("/api/lookup?kind=activity&number=2026A99999"),
        404,
    )
    # the node answer gives the debate its address, and the motion its MADE_IN
    node = api.get_json(f"/api/nodes/activities/{_key(DEBATE)}")
    assert node["path"] == "/activiteiten/2026A01323"
    assert node["title"].startswith(
        "Wetgevingsoverleg van 23 maart 2026: Wet weerbaarheid"
    )
    made = {
        (b["relation"], b["direction"], b["collection"]): b["total"]
        for b in node["neighbors"]["buckets"]
    }
    assert made[("MADE_IN", "inbound", "documents")] == 4  # record, verslag, 2 motions
    assert made[("MADE_IN", "inbound", "commitments")] == 1
    # the sitemap lists the debate (something to read), not the vote
    listed = [row["props"]["number"] for row in sitemaps.activities(store)]
    assert listed == ["2026A01323"]


def test_a_commitment_names_its_debate_and_the_letter_that_fulfils_it(
    api: Api,
) -> None:
    commitment = api.get_json(f"/api/commitments/{_key(COMMITMENT)}")
    # made in the debate, registered weeks later
    assert (commitment["date"], commitment["registered_on"]) == (
        "2026-03-23",
        "2026-04-10",
    )
    activity = commitment["activity"]
    assert (activity["kind"], activity["number"], activity["path"]) == (
        "Wetgevingsoverleg",
        "2026A01323",
        "/activiteiten/2026A01323",
    )
    assert activity["agenda_title"].endswith("Cyberbeveiligingswet (36764)")
    (letter,) = commitment["fulfilled_by"]
    assert (letter["kind"], letter["sequence"], letter["path"]) == (
        "Brief regering",
        33,
        "/kamerstukken/36764/33",
    )
    listed = api.get_json("/api/commitments", facets="false")["items"]
    assert listed[0]["fulfilled_by"] == commitment["fulfilled_by"]


def test_the_dossiers_the_kamer_relates_name_the_letter_and_the_motion(
    api: Api,
) -> None:
    """The edge between the dossiers says which letter goes into which motion; the node
    answer gives it (Verbonden), the head of the dossier only counts the pairs."""
    other = api.get_json("/api/dossiers/32761")
    (related,) = [r for r in other["relations"] if r["relation"] == "related_to"]
    assert (related["direction"], related["dossier"]["number"], related["cases"]) == (
        "outgoing",
        "36764",
        1,
    )
    node = api.get_json("/api/nodes/dossiers/32761")
    (edge,) = [
        item
        for bucket in node["neighbors"]["buckets"]
        if (bucket["relation"], bucket["collection"]) == ("RELATED_TO", "dossiers")
        for item in bucket["items"]
    ]
    (pair,) = edge["meta"]["pairs"]
    assert pair["from"] == {
        "paper": f"documents/{_key(LETTER_12)}",
        "kind": "Brief regering",
        "dossier_number": "32761",
        "dossier_suffix": None,
        "sequence": 12,
    }
    assert (pair["to"]["paper"], pair["to"]["sequence"]) == (
        f"documents/{_key(DOCUMENT_28)}",
        28,
    )

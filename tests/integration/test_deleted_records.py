"""A dossier, faction, person, seat, committee, vote or decision the Tweede Kamer deleted (a
record with its id and ``Verwijderd``, nothing else) is no node and no edge, and what an
earlier run wrote of it goes. The real ``normalize tk`` and ``normalize tk-dossiers`` on
stored records."""

from __future__ import annotations

import datetime as dt
import time
from typing import Any

from lawgraph.config.constants import (
    RAW_KIND_TK_COMMISSIE,
    RAW_KIND_TK_DOCUMENT,
    RAW_KIND_TK_DOSSIER,
    RAW_KIND_TK_FRACTIE,
    RAW_KIND_TK_FRACTIEZETELPERSOON,
    RAW_KIND_TK_PERSOON,
    RAW_KIND_TK_STEMMING,
    SOURCE_TK,
)
from lawgraph.core.models import make_node_key
from lawgraph.db import ArangoStore, RawSourceWriter, raw_source_doc
from tests.integration.seed import uid

KEPT_DOSSIER = {"Id": uid(1, 3), "Nummer": 36100, "Titel": "Rechtsstaat en Rechtsorde"}
GONE_DOSSIER = {"Id": uid(2, 3), "Nummer": 36101, "Titel": "Een dossier dat verdween"}
OLD_50PLUS, NEW_50PLUS, VVD, GONE_FACTION = uid(1, 8), uid(2, 8), uid(3, 8), uid(4, 8)
FABER, ELLIAN, GONE_PERSON = uid(1, 9), uid(2, 9), uid(3, 9)
FABER_SEAT, ELLIAN_SEAT, ELLIAN_OLD_SEAT = uid(1, 5), uid(2, 5), uid(3, 5)


def _faction(record_id: str, label: str, start: str, end: str | None) -> dict:
    return {
        "Id": record_id,
        "Afkorting": label,
        "NaamNL": label,
        "DatumActief": f"{start}T00:00:00+02:00",
        "DatumInactief": f"{end}T00:00:00+02:00" if end else None,
        "GewijzigdOp": f"{end or start}T00:00:00+02:00",
    }


def _seat(record_id: str, person: str, faction: str, start: str) -> dict[str, Any]:
    return {
        "Id": record_id,
        "Persoon_Id": person,
        "FractieZetel": {"Fractie_Id": faction},
        "Van": f"{start}T00:00:00+02:00",
        "TotEnMet": None,
        "Functie": "Lid",
    }


# A paper signed by the person the Kamer later deletes.
PAPER = {
    "Id": uid(1, 1),
    "Soort": "Brief lid / fractie",
    "Titel": KEPT_DOSSIER["Titel"],
    "Onderwerp": "Brief over de rechtsstaat",
    "Datum": "2026-09-10T00:00:00+02:00",
    "Verwijderd": False,
    "Zaak": [],
    "DocumentActor": [
        {"Persoon_Id": GONE_PERSON, "ActorNaam": "X", "Relatie": "Eerste ondertekenaar"}
    ],
}


def _deleted(record_id: str) -> dict[str, Any]:
    """A record the Tweede Kamer deleted, as the API sends it: its id and nothing else."""
    return {
        "Id": record_id,
        "Nummer": None,
        "Afkorting": None,
        "Achternaam": None,
        "Persoon_Id": None,
        "FractieZetel": None,
        "GewijzigdOp": "2026-09-15T09:51:40.497+02:00",
        "Verwijderd": True,
    }


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


def _records() -> list[tuple[str, dict[str, Any]]]:
    return [
        (RAW_KIND_TK_DOSSIER, KEPT_DOSSIER),
        (RAW_KIND_TK_DOSSIER, GONE_DOSSIER),
        (
            RAW_KIND_TK_FRACTIE,
            _faction(OLD_50PLUS, "50PLUS", "2012-09-20", "2021-05-11"),
        ),
        (RAW_KIND_TK_FRACTIE, _faction(NEW_50PLUS, "50PLUS", "2025-11-12", None)),
        (RAW_KIND_TK_FRACTIE, _faction(VVD, "VVD", "1948-01-01", None)),
        (RAW_KIND_TK_FRACTIE, _faction(GONE_FACTION, "OUD", "2010-01-01", None)),
        (RAW_KIND_TK_PERSOON, {"Id": FABER, "Voornamen": "M.", "Achternaam": "Faber"}),
        (
            RAW_KIND_TK_PERSOON,
            {"Id": ELLIAN, "Voornamen": "I.", "Achternaam": "Ellian"},
        ),
        (RAW_KIND_TK_PERSOON, {"Id": GONE_PERSON, "Voornamen": "X", "Achternaam": "Y"}),
        (
            RAW_KIND_TK_FRACTIEZETELPERSOON,
            _seat(FABER_SEAT, FABER, NEW_50PLUS, "2025-11-12"),
        ),
        (
            RAW_KIND_TK_FRACTIEZETELPERSOON,
            _seat(ELLIAN_SEAT, ELLIAN, VVD, "2023-12-06"),
        ),
        (
            RAW_KIND_TK_FRACTIEZETELPERSOON,
            _seat(ELLIAN_OLD_SEAT, ELLIAN, GONE_FACTION, "2010-01-01"),
        ),
        (RAW_KIND_TK_DOCUMENT, PAPER),
    ]


def _edges_at(store: ArangoStore, node_id: str) -> list[str]:
    return list(
        store.query(
            "FOR e IN edges FILTER e._from == @id OR e._to == @id RETURN e.relation",
            {"id": node_id},
        )
    )


def _seats(store: ArangoStore, person: str) -> list[str]:
    return sorted(
        store.query(
            """
            FOR e IN edges
                FILTER e._from == @id AND e.relation == "MEMBER_OF"
                FILTER STARTS_WITH(e._to, "factions/")
                RETURN e._to
            """,
            {"id": f"members/{make_node_key(person)}"},
        )
    )


def test_what_the_kamer_deleted_leaves_the_graph(database: str, cli: Any) -> None:
    store = ArangoStore()
    _write(store, _records())
    cli("normalize", "tk")
    cli("normalize", "tk-dossiers")

    gone_person = f"members/{make_node_key(GONE_PERSON)}"
    assert store.get_node("dossiers", "36101") is not None
    assert store.get_node("factions", "oud") is not None
    assert _edges_at(store, gone_person) == ["AUTHORED"]
    assert _seats(store, ELLIAN) == ["factions/oud", "factions/vvd"]

    # The Kamer deletes a dossier, a faction and the old record of 50PLUS, a person and a
    # seat: each becomes a record with its id and nothing else.
    _write(
        store,
        [
            (RAW_KIND_TK_DOSSIER, _deleted(GONE_DOSSIER["Id"])),
            (RAW_KIND_TK_FRACTIE, _deleted(GONE_FACTION)),
            (RAW_KIND_TK_FRACTIE, _deleted(OLD_50PLUS)),
            (RAW_KIND_TK_PERSOON, _deleted(GONE_PERSON)),
            (RAW_KIND_TK_FRACTIEZETELPERSOON, _deleted(ELLIAN_OLD_SEAT)),
        ],
    )
    cli("normalize", "tk")
    cli("normalize", "tk-dossiers")

    assert store.get_node("dossiers", "36101") is None
    assert store.get_node("dossiers", "36100") is not None
    assert store.get_node("factions", "oud") is None
    assert store.get_node(*gone_person.split("/")) is None
    assert _edges_at(store, gone_person) == []
    # 50PLUS is its new record now; the seats on the faction stay
    fifty = store.get_node("factions", "50plus")
    assert fifty is not None
    assert fifty.props["external_ids"] == [NEW_50PLUS]
    assert _seats(store, FABER) == ["factions/50plus"]
    assert _seats(store, ELLIAN) == ["factions/vvd"]
    # no node is made of a deleted record
    for collection, keys in (
        ("dossiers", ["36100"]),
        ("factions", ["50plus", "vvd"]),
        ("members", sorted(make_node_key(p) for p in (FABER, ELLIAN))),
    ):
        stored = store.query(f"FOR n IN {collection} SORT n._key RETURN n._key")
        assert list(stored) == keys, collection


# ── Votes and decisions ──────────────────────────────────────────────────────

CDA, D66 = uid(5, 8), uid(6, 8)
KEPT_DECISION, EMPTIED_DECISION, STRUCK_DECISION = uid(1, 7), uid(2, 7), uid(3, 7)
COMMITTEE, GONE_COMMITTEE = uid(1, 4), uid(2, 4)


def _besluit(decision: str, **fields: Any) -> dict[str, Any]:
    return {"Id": decision, "BesluitSoort": "Stemmen - aangenomen", **fields}


def _vote(
    number: int, decision: str, faction: str, label: str, seats: int
) -> dict[str, Any]:
    return {
        "Id": uid(number, 6),
        "Besluit_Id": decision,
        "Soort": "Voor",
        "FractieGrootte": seats,
        "ActorFractie": label,
        "Fractie_Id": faction,
        "Persoon_Id": None,
        "GewijzigdOp": "2026-09-23T09:00:00+02:00",
        "Besluit": _besluit(decision),
    }


VOTES = [
    _vote(1, KEPT_DECISION, VVD, "VVD", 22),
    _vote(2, KEPT_DECISION, CDA, "CDA", 18),
    _vote(3, KEPT_DECISION, D66, "D66", 26),
    _vote(4, EMPTIED_DECISION, VVD, "VVD", 22),
    _vote(5, EMPTIED_DECISION, CDA, "CDA", 18),
    _vote(6, STRUCK_DECISION, D66, "D66", 26),
]


def _vote_records() -> list[tuple[str, dict[str, Any]]]:
    return [
        (RAW_KIND_TK_FRACTIE, _faction(VVD, "VVD", "1948-01-01", None)),
        (RAW_KIND_TK_FRACTIE, _faction(CDA, "CDA", "1980-10-11", None)),
        (RAW_KIND_TK_FRACTIE, _faction(D66, "D66", "1966-10-14", None)),
        (RAW_KIND_TK_COMMISSIE, {"Id": COMMITTEE, "NaamNL": "Commissie voor J&V"}),
        (
            RAW_KIND_TK_COMMISSIE,
            {"Id": GONE_COMMITTEE, "NaamNL": "Verdwenen commissie"},
        ),
        *((RAW_KIND_TK_STEMMING, vote) for vote in VOTES),
    ]


def _deletions() -> list[tuple[str, dict[str, Any]]]:
    """The Kamer deletes the CDA vote on the kept decision, both votes on the emptied one,
    the Besluit of the struck one (its vote names it deleted) and a committee."""
    struck = VOTES[5] | {"Besluit": _besluit(STRUCK_DECISION, Verwijderd=True)}
    return [
        (RAW_KIND_TK_STEMMING, _deleted(VOTES[1]["Id"])),
        (RAW_KIND_TK_STEMMING, _deleted(VOTES[3]["Id"])),
        (RAW_KIND_TK_STEMMING, _deleted(VOTES[4]["Id"])),
        (RAW_KIND_TK_STEMMING, struck),
        (RAW_KIND_TK_COMMISSIE, _deleted(GONE_COMMITTEE)),
    ]


def _voters(store: ArangoStore, decision: str) -> list[str]:
    return sorted(
        store.query(
            'FOR e IN edges FILTER e._to == @id AND e.relation == "VOTED" RETURN e._from',
            {"id": f"decisions/{make_node_key('decision', decision)}"},
        )
    )


def _assert_votes_follow_the_deletions(store: ArangoStore) -> None:
    kept = store.get_node("decisions", make_node_key("decision", KEPT_DECISION))
    assert kept is not None
    assert kept.props["tally"] == {"Voor": 48}
    assert kept.props["voters"] == {"Voor": 2}
    assert _voters(store, KEPT_DECISION) == ["factions/d66", "factions/vvd"]
    for gone in (EMPTIED_DECISION, STRUCK_DECISION):
        node_id = f"decisions/{make_node_key('decision', gone)}"
        assert store.get_node(*node_id.split("/")) is None
        assert _edges_at(store, node_id) == []
    assert store.get_node("committees", make_node_key(GONE_COMMITTEE)) is None
    assert store.get_node("committees", make_node_key(COMMITTEE)) is not None


def test_a_deleted_vote_leaves_its_decision_and_a_decision_without_votes_goes(
    database: str, cli: Any
) -> None:
    store = ArangoStore()
    _write(store, _vote_records())
    cli("normalize", "tk-dossiers")
    assert _voters(store, KEPT_DECISION) == [
        "factions/cda",
        "factions/d66",
        "factions/vvd",
    ]
    assert _voters(store, EMPTIED_DECISION) == ["factions/cda", "factions/vvd"]
    assert _voters(store, STRUCK_DECISION) == ["factions/d66"]

    _write(store, _deletions())
    cli("normalize", "tk-dossiers")
    _assert_votes_follow_the_deletions(store)


def test_an_incremental_run_removes_what_the_kamer_deleted_in_its_window(
    database: str, cli: Any
) -> None:
    """A deleted vote names no decision: the edge it made does."""
    store = ArangoStore()
    _write(store, _vote_records())
    cli("normalize", "tk-dossiers")

    time.sleep(1.1)  # fetched_at has a precision of a second
    window = dt.datetime.now(dt.timezone.utc).replace(microsecond=0).isoformat()
    _write(store, _deletions())
    cli("normalize", "tk-dossiers", "--since", window)
    _assert_votes_follow_the_deletions(store)

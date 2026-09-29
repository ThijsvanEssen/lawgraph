"""A dossier, faction, person or seat the Tweede Kamer deleted (a record with its id and
``Verwijderd``, nothing else) is no node and no edge, and what an earlier run wrote of it
goes. The real ``normalize tk`` and ``normalize tk-dossiers`` on stored records."""

from __future__ import annotations

from typing import Any

from lawgraph.config.constants import (
    RAW_KIND_TK_DOCUMENT,
    RAW_KIND_TK_DOSSIER,
    RAW_KIND_TK_FRACTIE,
    RAW_KIND_TK_FRACTIEZETELPERSOON,
    RAW_KIND_TK_PERSOON,
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

"""A seat no member held, for real: ``normalize tk-dossiers`` keeps the FractieZetelVacature
records on their faction (``vacancies``), the last vacant day the one before the successor
took the seat, also on a run over a window that holds none of them; and
``/api/cabinets/{key}/seats`` counts them among the faction's seats."""

from __future__ import annotations

import datetime as dt
from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    RAW_KIND_TK_FRACTIE,
    RAW_KIND_TK_FRACTIEZETELPERSOON,
    RAW_KIND_TK_FRACTIEZETELVACATURE,
    RAW_KIND_TK_PERSOON,
    RELATION_SERVED_IN,
)
from lawgraph.db import GraphStore, make_edge_doc
from tests.integration.seed import uid
from tests.integration.test_member_periods import _faction, _person
from tests.integration.test_member_seats_window import _write

D66 = uid(1, 7)


def _vacancy(n: int, start: str, until: str | None) -> dict[str, Any]:
    return {
        "Id": uid(n, 6),
        "Van": f"{start}T00:00:00+01:00",
        "TotEnMet": f"{until}T00:00:00+01:00" if until else None,
        "Functie": "Lid",
        "Verwijderd": False,
        "FractieZetel": {"Id": uid(n, 5), "Fractie_Id": D66},
    }


def test_a_vacant_seat_is_its_factions(database: str, cli: Any) -> None:
    store = GraphStore()
    _write(
        store,
        (RAW_KIND_TK_FRACTIE, _faction(D66, "D66", "1966-10-14", None, 26)),
        (RAW_KIND_TK_FRACTIEZETELVACATURE, _vacancy(1, "2026-02-23", "2026-02-25")),
        # a record of the source that ends before it begins
        (RAW_KIND_TK_FRACTIEZETELVACATURE, _vacancy(2, "2026-02-23", "2026-02-22")),
    )
    cli("normalize", "tk-dossiers")
    since = dt.datetime.now(dt.timezone.utc).isoformat()
    # a run over a window without them keeps them
    cli("normalize", "tk-dossiers", "--since", since)
    (vacancies,) = store.query(
        "SELECT props -> 'vacancies' FROM factions WHERE key = 'd66'"
    )
    assert vacancies == [{"from_date": "2026-02-23", "to_date": "2026-02-24"}]

    store.bulk_insert_or_update_nodes(
        "cabinets",
        [
            {
                "_key": "jetten",
                "type": "cabinet",
                "labels": [],
                "props": {"name": "kabinet-Jetten", "from_date": "2026-02-23"},
            }
        ],
    )
    store.bulk_insert_or_update_nodes(
        "members",
        [{"_key": "minister", "type": "member", "labels": [], "props": {"name": "m"}}],
    )
    store.bulk_insert_or_update_edges(
        [
            make_edge_doc(
                "members/minister",
                "cabinets/jetten",
                RELATION_SERVED_IN,
                source="t",
                meta={
                    "posts": [
                        {
                            "party": {"short": "D66", "faction": "d66"},
                            "from_date": "2026-02-23",
                            "to_date": None,
                        }
                    ]
                },
            )
        ]
    )
    app.dependency_overrides[get_store] = lambda: store
    try:
        seats = TestClient(app).get("/api/cabinets/jetten/seats").json()
    finally:
        app.dependency_overrides.pop(get_store, None)
    first = seats["tk"][0]
    # no member sat for D66 that day, its vacant seat still counts for the coalition
    assert (first["from_date"], first["coalition"]) == ("2026-02-23", 1)
    assert first["factions"] == [
        {
            "key": "d66",
            "abbreviation": "D66",
            "seats": 1,
            "vacant": 1,
            "coalition": True,
        }
    ]


BBB = uid(2, 7)


def _on_seat(
    n: int, seat: int, pid: str, start: str, end: str | None
) -> dict[str, Any]:
    return {
        "Id": uid(n, 5),
        "Persoon_Id": pid,
        "FractieZetel_Id": uid(seat, 4),
        "FractieZetel": {"Id": uid(seat, 4), "Fractie_Id": BBB},
        "Van": f"{start}T00:00:00+01:00",
        "TotEnMet": f"{end}T00:00:00+01:00" if end else None,
        "Functie": "Lid",
    }


def _vacancy_of(n: int, seat: int, start: str, until: str | None) -> dict[str, Any]:
    return {
        "Id": uid(n, 6),
        "Van": f"{start}T00:00:00+01:00",
        "TotEnMet": f"{until}T00:00:00+01:00" if until else None,
        "Verwijderd": False,
        "FractieZetel": {"Id": uid(seat, 4), "Fractie_Id": BBB},
    }


def test_a_seat_is_held_or_vacant_never_both(database: str, cli: Any) -> None:
    """The source holds vacancies that overlap the seat's own members (BBB, 2025: one never
    closed while Helder and then Oostenbrink sat; D66, 2026: one from the predecessor's
    last day). A seat counts once on a day, so every stretch of a cabinet adds up to the
    150 seats of the Kamer: also after a nightly run over a window, which keeps every
    vacancy again."""
    store = GraphStore()
    people = {name: uid(n, 3) for n, name in enumerate("PQRS", start=1)}
    _write(
        store,
        (RAW_KIND_TK_FRACTIE, _faction(BBB, "BBB", "2019-01-01", None, 2)),
        *[(RAW_KIND_TK_PERSOON, _person(pid, n, n)) for n, pid in people.items()],
        (RAW_KIND_TK_FRACTIEZETELPERSOON, _on_seat(1, 1, people["P"], "2023-09-01", "2025-03-04")),
        (RAW_KIND_TK_FRACTIEZETELPERSOON, _on_seat(2, 1, people["Q"], "2025-03-05", None)),
        (RAW_KIND_TK_FRACTIEZETELPERSOON, _on_seat(3, 2, people["R"], "2023-09-01", "2026-02-16")),
        (RAW_KIND_TK_FRACTIEZETELPERSOON, _on_seat(4, 2, people["S"], "2026-02-25", None)),
        # never closed, while P and then Q held the seat
        (RAW_KIND_TK_FRACTIEZETELVACATURE, _vacancy_of(11, 1, "2025-02-05", None)),
        # from R's last day until S took the seat
        (RAW_KIND_TK_FRACTIEZETELVACATURE, _vacancy_of(12, 2, "2026-02-16", "2026-02-25")),
    )  # fmt: skip
    cli("normalize", "tk-dossiers")
    as_the_source_said = [
        {"from_date": "2025-02-05", "to_date": None},
        {"from_date": "2026-02-16", "to_date": "2026-02-24"},
    ]
    # as an earlier code kept them, the source's periods as they are
    faction = store.get_document("factions", "bbb")
    assert faction is not None
    store.bulk_insert_or_update_nodes(
        "factions",
        [
            {
                "_key": "bbb",
                "type": faction.get("type", "faction"),
                "labels": faction.get("labels") or [],
                "props": {**faction["props"], "vacancies": as_the_source_said},
            }
        ],
    )
    # the nightly: a run over a window that holds none of the records
    cli(
        "normalize",
        "tk-dossiers",
        "--since",
        dt.datetime.now(dt.timezone.utc).isoformat(),
    )
    (vacancies,) = store.query(
        "SELECT props -> 'vacancies' FROM factions WHERE key = 'bbb'"
    )
    assert vacancies == [{"from_date": "2026-02-17", "to_date": "2026-02-24"}]

    store.bulk_insert_or_update_nodes(
        "cabinets",
        [{"_key": "schoof", "type": "cabinet", "labels": [],
          "props": {"name": "kabinet-Schoof", "from_date": "2024-07-02"}}],
    )  # fmt: skip
    app.dependency_overrides[get_store] = lambda: store
    try:
        seats = TestClient(app).get("/api/cabinets/schoof/seats").json()
    finally:
        app.dependency_overrides.pop(get_store, None)
    assert seats["tk"]
    for stretch in seats["tk"]:
        # a seat is held or vacant, never both: the seats held and the vacant ones, and
        # the parties' seats (their vacant ones among them) with those of no faction, are
        # each the Kamer
        held = sum(f["seats"] - f["vacant"] for f in stretch["factions"])
        of_factions = sum(f["vacant"] for f in stretch["factions"])
        assert held + stretch["vacant"] == 150
        assert (
            stretch["coalition"]
            + stretch["opposition"]
            + (stretch["vacant"] - of_factions)
            == 150
        )
        (bbb,) = [f for f in stretch["factions"] if f["key"] == "bbb"]
        assert bbb["seats"] == 2, stretch["from_date"]
    vacant = [(s["from_date"], s["to_date"]) for s in seats["tk"]
              if any(f["vacant"] for f in s["factions"])]  # fmt: skip
    assert vacant == [("2026-02-17", "2026-02-24")]

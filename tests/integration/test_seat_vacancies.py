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
    RAW_KIND_TK_FRACTIEZETELVACATURE,
    RELATION_SERVED_IN,
)
from lawgraph.db import GraphStore, make_edge_doc
from tests.integration.seed import uid
from tests.integration.test_member_periods import _faction
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

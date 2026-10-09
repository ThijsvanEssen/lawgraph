"""The seats of a cabinet's coalition, for real: the coalition on a day is the factions whose
party held a post in the cabinet (``SERVED_IN`` ``meta.posts``), the seats those the members
held (``faction_memberships``). A split-off is opposition; a party that leaves the cabinet
leaves the coalition. Both ``/api/cabinets/{key}/seats`` and the flag on
``/api/parliament/seats``."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import RELATION_SERVED_IN
from lawgraph.db import GraphStore, make_edge_doc


def _node(key: str, node_type: str, **props: Any) -> dict[str, Any]:
    return {"_key": key, "type": node_type, "labels": [], "props": props}


def _post(faction: str, short: str, start: str, end: str | None = None) -> dict:
    return {
        "party": {"short": short, "faction": faction},
        "from_date": start,
        "to_date": end,
    }


def _member(key: str, *periods: tuple[str, str, str | None]) -> dict[str, Any]:
    return _node(
        key,
        "member",
        name=key,
        faction_memberships=[
            {"faction_key": f, "from_date": start, "to_date": end}
            for f, start, end in periods
        ],
    )


def _seed(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "cabinets",
        [
            _node("schoof", "cabinet", name="kabinet-Schoof", from_date="2024-07-02"),
            _node(
                "balkenende_iii",
                "cabinet",
                name="kabinet-Balkenende III",
                from_date="2006-07-07",
                to_date="2007-02-22",
            ),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "factions",
        [
            _node("pvv", "faction", name="PVV", abbreviation="PVV", active=True),
            _node("vvd", "faction", name="VVD", abbreviation="VVD", active=True),
            _node("groep", "faction", name="Groep", abbreviation="Groep", active=True),
            _node("sp", "faction", name="SP", abbreviation="SP", active=True),
            _node(
                "ek_vvd",
                "faction",
                name="VVD-fractie",
                abbreviation="VVD",
                chamber="EK",
                seats=10,
                active=True,
                retrieved_on="2026-10-01",
            ),
            _node(
                "ek_sp",
                "faction",
                name="SP-fractie",
                abbreviation="SP",
                chamber="EK",
                seats=3,
                active=True,
                retrieved_on="2026-10-01",
            ),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "members",
        [
            _member(
                "a", ("pvv", "2023-12-06", "2025-01-31"), ("groep", "2025-02-01", None)
            ),
            _member("b", ("pvv", "2023-12-06", None)),
            _member("c", ("vvd", "2023-12-06", None)),
            _member("d", ("sp", "2023-12-06", None)),
            _member("minister_pvv", ("pvv", "2023-12-06", "2024-07-01")),
            _member("minister_vvd", ("vvd", "2023-12-06", "2024-07-01")),
        ],
    )
    store.bulk_insert_or_update_edges(
        [
            make_edge_doc(
                "members/minister_pvv",
                "cabinets/schoof",
                RELATION_SERVED_IN,
                source="t",
                meta={"posts": [_post("pvv", "PVV", "2024-07-02", "2025-06-03")]},
            ),
            make_edge_doc(
                "members/minister_vvd",
                "cabinets/schoof",
                RELATION_SERVED_IN,
                source="t",
                meta={"posts": [_post("vvd", "VVD", "2024-07-02")]},
            ),
        ]
    )


def test_the_coalition_seats_of_a_cabinet_and_on_a_day(database: str) -> None:
    store = GraphStore()
    _seed(store)
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        seats = client.get("/api/cabinets/schoof/seats").json()
        old = client.get("/api/cabinets/balkenende_iii/seats").json()
        on_day = client.get(
            "/api/parliament/seats", params={"date": "2025-03-01"}
        ).json()
        ek = client.get("/api/parliament/seats", params={"chamber": "EK"}).json()
    finally:
        app.dependency_overrides.pop(get_store, None)

    assert seats["majority"] == {"TK": 76, "EK": 38}
    stretches = [(s["from_date"], s["coalition"], s["opposition"]) for s in seats["tk"]]
    # the split-off goes to the opposition; the PVV leaves with its last post
    assert stretches[:3] == [
        ("2024-07-02", 3, 1),
        ("2025-02-01", 2, 2),
        ("2025-06-04", 1, 3),
    ]
    assert seats["ek"][0]["coalition"] == 10 and seats["ek"][0]["opposition"] == 3
    # a cabinet that began before every seat is known: no Tweede Kamer bar
    assert old["tk"] is None

    assert on_day["cabinet"] == {"key": "schoof", "name": "kabinet-Schoof"}
    flags = {f["key"]: f["coalition"] for f in on_day["factions"]}
    assert flags == {"pvv": True, "vvd": True, "groep": False, "sp": False}
    assert {f["key"]: f["coalition"] for f in ek["factions"]} == {
        "ek_vvd": True,
        "ek_sp": False,
    }

"""The seats of a cabinet and of the hall on the days a cabinet hands over: a cabinet that
its successor follows on its last day has stretches up to the day before (that day is the
successor's), and the hall of a day gives per faction its seats held and its vacant seats,
so that together they are the faction's seats as the cabinet's stretches count them."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import RELATION_SERVED_IN
from lawgraph.db import GraphStore, make_edge_doc
from tests.integration.test_coalition_seats import _member, _node, _post


def _seed(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "cabinets",
        [
            _node(
                "rutte_iv",
                "cabinet",
                name="kabinet-Rutte IV",
                from_date="2023-12-06",
                to_date="2024-07-02",
            ),
            _node("schoof", "cabinet", name="kabinet-Schoof", from_date="2024-07-02"),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "factions",
        [
            # the seat the minister left is vacant until the successor takes it
            _node(
                "vvd",
                "faction",
                name="VVD",
                abbreviation="VVD",
                active=True,
                vacancies=[{"from_date": "2024-07-02", "to_date": "2024-07-03"}],
            ),
            _node("sp", "faction", name="SP", abbreviation="SP", active=True),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "members",
        [
            _member("c", ("vvd", "2023-12-06", None)),
            _member("d", ("sp", "2023-12-06", None)),
            _member("heinen", ("vvd", "2023-12-06", "2024-07-01")),
            _member("successor", ("vvd", "2024-07-04", None)),
        ],
    )
    store.bulk_insert_or_update_edges(
        [
            make_edge_doc(
                "members/c",
                "cabinets/rutte_iv",
                RELATION_SERVED_IN,
                source="t",
                meta={"posts": [_post("vvd", "VVD", "2023-12-06", "2024-07-02")]},
            ),
            make_edge_doc(
                "members/heinen",
                "cabinets/schoof",
                RELATION_SERVED_IN,
                source="t",
                meta={"posts": [_post("vvd", "VVD", "2024-07-02")]},
            ),
        ]
    )


def _get(client: TestClient, path: str, **params: Any) -> dict[str, Any]:
    response = client.get(path, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def test_the_seats_on_the_days_a_cabinet_hands_over(database: str) -> None:
    store = GraphStore()
    _seed(store)
    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        rutte = _get(client, "/api/cabinets/rutte_iv/seats")
        schoof = _get(client, "/api/cabinets/schoof/seats")
        before = _get(client, "/api/parliament/seats", date="2024-07-01")
        handover = _get(client, "/api/parliament/seats", date="2024-07-02")
    finally:
        app.dependency_overrides.pop(get_store, None)

    # the last day of Rutte IV is Schoof's first: its stretches end the day before
    assert rutte["to_date"] == "2024-07-02"
    assert rutte["tk"][-1]["to_date"] == "2024-07-01"
    assert [(s["from_date"], s["to_date"], s["coalition"]) for s in rutte["tk"]] == [
        ("2023-12-06", "2024-07-01", 2)
    ]
    # Schoof begins that day, the vacant seat still the VVD's
    assert schoof["tk"][0]["from_date"] == "2024-07-02"
    assert schoof["tk"][0]["coalition"] == 2

    def hall(answer: dict[str, Any]) -> dict[str, tuple[int, int]]:
        return {f["key"]: (f["seats"], f["vacant"]) for f in answer["factions"]}

    # the hall: the seats held and the vacant ones, together the faction's
    assert hall(before) == {"vvd": (2, 0), "sp": (1, 0)}
    assert hall(handover) == {"vvd": (1, 1), "sp": (1, 0)}
    assert handover["assigned_seats"] == 2

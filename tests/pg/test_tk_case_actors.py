"""``retrieve tk-case-actors`` and ``normalize tk-case-actors`` on a real PostgreSQL: the
actors of a case stored as a raw record of their own, and written as AUTHORED and LED_BY
edges between the nodes that exist."""

from __future__ import annotations

import datetime as dt
from typing import Any

from lawgraph.db import GraphStore
from lawgraph.pipelines.normalize.tk_case_actors import TKCaseActorsNormalizePipeline
from lawgraph.pipelines.retrieve.tk_case_actors import TKCaseActorsRetrievePipeline


class _Client:
    """The Gegevensmagazijn as ``fetch_case_actors`` reads it."""

    on_total: Any = None

    def __init__(self) -> None:
        self.since: list[Any] = []

    def fetch_case_actors(self, since: Any = None) -> Any:
        self.since.append(since)
        return iter(
            [
                {
                    "Id": "motion",
                    "ZaakActor": [
                        {
                            "Relatie": "Voortouwcommissie",
                            "ActorAfkorting": "TK",
                            "Commissie_Id": "plenary",
                        },
                        {
                            "Relatie": "Indiener",
                            "Persoon_Id": "member",
                            "Fractie_Id": "f",
                        },
                        {"Relatie": "Medeindiener", "Persoon_Id": "unknown"},
                    ],
                },
                {
                    "Id": "bill",
                    "ZaakActor": [
                        {
                            "Relatie": "Voortouwcommissie",
                            "ActorAfkorting": "VWS",
                            "Commissie_Id": "vws",
                        },
                        {
                            "Relatie": "Indiener",
                            "Persoon_Id": "minister",
                            "Functie": "minister voor Medische Zorg",
                        },
                    ],
                },
                {
                    "Id": "not-stored",
                    "ZaakActor": [{"Relatie": "Indiener", "Persoon_Id": "member"}],
                },
                {
                    "Id": "gone",
                    "Verwijderd": True,
                    "ZaakActor": [{"Relatie": "Indiener", "Persoon_Id": "member"}],
                },
                {"ZaakActor": []},  # no id: not stored
            ]
        )


def _nodes(
    store: GraphStore, collection: str, kind: str, keys: tuple[str, ...]
) -> None:
    store.bulk_insert_or_update_nodes(
        collection,
        [{"_key": key, "type": kind, "labels": ["TK"], "props": {}} for key in keys],
    )


def test_the_actors_are_stored_and_written_as_edges(store: GraphStore) -> None:
    _nodes(store, "cases", "case", ("motion", "bill", "gone"))
    _nodes(store, "members", "member", ("member", "minister"))
    _nodes(store, "committees", "committee", ("vws", "plenary"))
    client = _Client()
    since = dt.datetime(2026, 10, 1, tzinfo=dt.timezone.utc)
    retrieved = TKCaseActorsRetrievePipeline(store, client).run(since=since)  # type: ignore[arg-type]
    assert client.since == [since]
    assert retrieved.created == 4 and retrieved.skipped == 1

    result = TKCaseActorsNormalizePipeline(store=store).run()
    assert not result.errors
    edges = {
        (row["from_id"], row["relation"], row["to_id"], row["role"])
        for row in store.query(
            "SELECT from_id, relation, to_id, doc -> 'meta' ->> 'role' AS role "
            "FROM edges WHERE source = 'tk-case-actors'"
        )
    }
    # the submitters that are stored, with their role; the bill's committee, not the
    # plenary; nothing of a case not stored or deleted
    assert edges == {
        ("members/member", "AUTHORED", "cases/motion", "Indiener"),
        ("members/minister", "AUTHORED", "cases/bill", "Indiener"),
        ("cases/bill", "LED_BY", "committees/vws", None),
    }

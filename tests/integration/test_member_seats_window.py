"""A seat the Kamer records later, for a member and a faction stored before: ``normalize
tk-dossiers --since`` reads only the new seat record, and still makes the member's MEMBER_OF
edge to that faction (the member and the faction come from the database, not from the
window)."""

from __future__ import annotations

import datetime as dt
from typing import Any

from lawgraph.config.constants import (
    RAW_KIND_TK_FRACTIE,
    RAW_KIND_TK_FRACTIEZETELPERSOON,
    RAW_KIND_TK_PERSOON,
    SOURCE_TK,
)
from lawgraph.db import GraphStore, RawSourceWriter, raw_source_doc
from tests.integration.seed import uid
from tests.integration.test_member_periods import _faction, _person, _seat

VVD, PRO = uid(1, 8), uid(3, 8)
KLAVER = uid(4, 9)


def _write(store: GraphStore, *records: tuple[str, dict[str, Any]]) -> None:
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


def _member_of(store: GraphStore) -> set[tuple[str, str]]:
    return {
        (row["from_id"], row["to_id"])
        for row in store.query(
            "SELECT from_id, to_id FROM edges WHERE relation = 'MEMBER_OF'"
            " AND to_collection = 'factions'"
        )
    }


def test_a_new_seat_of_a_stored_member_is_linked_in_a_window(
    database: str, cli: Any
) -> None:
    store = GraphStore()
    _write(
        store,
        (RAW_KIND_TK_FRACTIE, _faction(VVD, "VVD", "1948-01-23", None, 22)),
        (RAW_KIND_TK_FRACTIE, _faction(PRO, "PRO", "2026-06-09", None, 20)),
        (RAW_KIND_TK_PERSOON, _person(KLAVER, "Jesse", "Klaver")),
        (
            RAW_KIND_TK_FRACTIEZETELPERSOON,
            _seat(10, KLAVER, VVD, "2020-01-01", "2026-06-08"),
        ),
    )
    cli("normalize", "tk-dossiers")
    before = _member_of(store)
    assert len(before) == 1

    since = dt.datetime.now(dt.timezone.utc).isoformat()
    # the next day: the Kamer records his seat in PRO; his record and PRO's do not change
    _write(
        store,
        (RAW_KIND_TK_FRACTIEZETELPERSOON, _seat(11, KLAVER, PRO, "2026-06-09", None)),
    )
    cli("normalize", "tk-dossiers", "--since", since)

    member = "members/" + KLAVER.lower().replace("-", "_")
    assert (member, "factions/pro") in _member_of(store)


def test_the_timeline_keeps_the_seats_before_the_window(
    database: str, cli: Any
) -> None:
    store = GraphStore()
    _write(
        store,
        (RAW_KIND_TK_FRACTIE, _faction(VVD, "VVD", "1948-01-23", None, 22)),
        (RAW_KIND_TK_FRACTIE, _faction(PRO, "PRO", "2026-06-09", None, 20)),
        (RAW_KIND_TK_PERSOON, _person(KLAVER, "Jesse", "Klaver")),
        (
            RAW_KIND_TK_FRACTIEZETELPERSOON,
            _seat(10, KLAVER, VVD, "2020-01-01", "2026-06-08"),
        ),
    )
    cli("normalize", "tk-dossiers")
    since = dt.datetime.now(dt.timezone.utc).isoformat()
    _write(
        store,
        (RAW_KIND_TK_FRACTIEZETELPERSOON, _seat(11, KLAVER, PRO, "2026-06-09", None)),
    )
    cli("normalize", "tk-dossiers", "--since", since)

    (row,) = store.query(
        "SELECT props -> 'faction_memberships' AS timeline, props ->> 'party' AS party"
        " FROM members"
    )
    assert [m["abbreviation"] for m in row["timeline"]] == ["VVD", "PRO"]
    assert row["party"] == "PRO"

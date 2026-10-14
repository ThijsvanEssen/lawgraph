"""The periods of members and factions as the Tweede Kamer dates them, read so they hold
together: a seat whose end the Kamer typed before its start (Kamp, VVD, 2006-11-30 to
2003-02-22), a fractievoorzitter still chairing after the next one started, a faction whose
record starts or ends a day off its seats (GroenLinks-PvdA and PRO), an ended faction with
the seats it once had, and the seats of the Kamer on a given day. The real
``normalize tk-dossiers`` on stored records, and the API on its nodes."""

from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.config.constants import (
    COLLECTION_FACTIONS,
    RAW_KIND_TK_FRACTIE,
    RAW_KIND_TK_FRACTIEZETELPERSOON,
    RAW_KIND_TK_PERSOON,
)
from lawgraph.core.models import make_node_key
from lawgraph.db import GraphStore
from tests.integration.seed import tk_faction, tk_person, tk_seat, uid, write_tk

VVD, GLPVDA, PRO = uid(1, 8), uid(2, 8), uid(3, 8)
KAMP, RUTTE, BLOK, KLAVER = uid(1, 9), uid(2, 9), uid(3, 9), uid(4, 9)


def _records() -> list[tuple[str, dict[str, Any]]]:
    return [
        (RAW_KIND_TK_FRACTIE, tk_faction(VVD, "VVD", "1948-01-23", None, 22)),
        # the record of GroenLinks-PvdA ends a day after its seats; PRO starts a day before
        (
            RAW_KIND_TK_FRACTIE,
            tk_faction(GLPVDA, "GroenLinks-PvdA", "2023-10-27", "2026-06-10", 20),
        ),
        (RAW_KIND_TK_FRACTIE, tk_faction(PRO, "PRO", "2026-06-09", None, 20)),
        (RAW_KIND_TK_PERSOON, tk_person(KAMP, "Henk", "Kamp")),
        (RAW_KIND_TK_PERSOON, tk_person(RUTTE, "Mark", "Rutte")),
        (RAW_KIND_TK_PERSOON, tk_person(BLOK, "Stef", "Blok")),
        (RAW_KIND_TK_PERSOON, tk_person(KLAVER, "Jesse", "Klaver")),
        # Kamp: two seats whose TotEnMet the Kamer typed before their Van
        (
            RAW_KIND_TK_FRACTIEZETELPERSOON,
            tk_seat(1, KAMP, VVD, "2003-01-30", "2003-05-26"),
        ),
        (
            RAW_KIND_TK_FRACTIEZETELPERSOON,
            tk_seat(2, KAMP, VVD, "2006-11-30", "2003-02-22"),
        ),
        (
            RAW_KIND_TK_FRACTIEZETELPERSOON,
            tk_seat(3, KAMP, VVD, "2007-02-23", "2003-02-22"),
        ),
        # Rutte chairs until 2010-10-13; Blok chairs from 2010-10-08
        (
            RAW_KIND_TK_FRACTIEZETELPERSOON,
            tk_seat(4, RUTTE, VVD, "2006-06-28", "2010-10-13", "Fractievoorzitter"),
        ),
        (
            RAW_KIND_TK_FRACTIEZETELPERSOON,
            tk_seat(5, BLOK, VVD, "2010-10-08", "2012-09-12", "Fractievoorzitter"),
        ),
        (
            RAW_KIND_TK_FRACTIEZETELPERSOON,
            tk_seat(6, KLAVER, GLPVDA, "2023-10-27", "2026-06-09", "Fractievoorzitter"),
        ),
        (
            RAW_KIND_TK_FRACTIEZETELPERSOON,
            tk_seat(7, KLAVER, PRO, "2026-06-10", None, "Fractievoorzitter"),
        ),
    ]


def _load(store: GraphStore) -> None:
    write_tk(store, _records())


def _periods(member: dict) -> list[tuple[str, str | None, str | None, str | None]]:
    return [
        (m["faction_key"], m["from_date"], m["to_date"], m["role"])
        for m in member["faction_memberships"]
    ]


def test_member_and_faction_periods_hold_together(database: str, cli: Any) -> None:
    store = GraphStore()
    _load(store)
    cli("normalize", "tk-dossiers")

    app.dependency_overrides[get_store] = lambda: store
    try:
        client = TestClient(app)
        kamp = client.get(f"/api/members/{make_node_key(KAMP)}").json()
        rutte = client.get(f"/api/members/{make_node_key(RUTTE)}").json()
        blok = client.get(f"/api/members/{make_node_key(BLOK)}").json()
        before = client.get("/api/parliament/seats?date=2026-06-09").json()
        after = client.get("/api/parliament/seats?date=2026-06-10").json()
        chairs = client.get("/api/parliament/seats?date=2010-10-10").json()
    finally:
        app.dependency_overrides.pop(get_store, None)

    # Kamp: the seat of 2006 ends the day before his next one starts; the seat of 2007 has
    # no end the Kamer gives and none to take from a later seat: it is left out, not
    # left open (he is no member today)
    assert _periods(kamp) == [
        ("vvd", "2003-01-30", "2003-05-26", "Lid"),
        ("vvd", "2006-11-30", "2007-02-22", "Lid"),
    ]
    # Rutte chairs until Blok does, and holds his seat as a member until it ends
    assert _periods(rutte) == [
        ("vvd", "2006-06-28", "2010-10-07", "Fractievoorzitter"),
        ("vvd", "2010-10-08", "2010-10-13", "Lid"),
    ]
    assert _periods(blok) == [("vvd", "2010-10-08", "2012-09-12", "Fractievoorzitter")]

    # a faction is active while its seats are held: GroenLinks-PvdA until the day before
    # PRO; an ended faction has no seats
    glpvda = store.get_node(COLLECTION_FACTIONS, "groenlinks_pvda")
    pro = store.get_node(COLLECTION_FACTIONS, "pro")
    assert glpvda is not None and pro is not None
    assert (glpvda.props["active_from"], glpvda.props["active_until"]) == (
        "2023-10-27",
        "2026-06-09",
    )
    assert glpvda.props["seats"] == 0
    assert (pro.props["active_from"], pro.props["active_until"]) == ("2026-06-10", None)
    assert pro.props["seats"] == 20

    # the seats on a day: the seats the members held that day
    assert before["as_of"] == "2026-06-09"
    assert [(f["key"], f["seats"]) for f in before["factions"]] == [
        ("groenlinks_pvda", 1)
    ]
    assert [(f["key"], f["seats"]) for f in after["factions"]] == [("pro", 1)]
    assert [(f["key"], f["seats"]) for f in chairs["factions"]] == [("vvd", 2)]
    assert chairs["assigned_seats"] == 2

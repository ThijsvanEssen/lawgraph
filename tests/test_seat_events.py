"""The kinds of the events that begin a stretch of seats: one enum for core and API."""

from __future__ import annotations

from lawgraph.api.schemas.cabinets import SeatEventDTO
from lawgraph.core.coalition import tk_events
from lawgraph.core.ek_seat_walk import _ORDER
from lawgraph.core.seat_events import SeatEventBasis, SeatEventKind

# The kinds the Eerste Kamer's pages give (``core.ek_mutations``).
EK_KINDS = {
    SeatEventKind.BEEDIGING,
    SeatEventKind.VERTREK,
    SeatEventKind.OVERSTAP,
    SeatEventKind.AFSPLITSING,
    SeatEventKind.HERNOEMING,
    SeatEventKind.SAMENVOEGING,
}


def test_every_kind_of_the_eerste_kamer_has_its_rank_within_a_day() -> None:
    assert set(_ORDER) == EK_KINDS


def test_the_api_answers_the_same_strings() -> None:
    event = SeatEventDTO(kind="beëdiging", date="2023-06-13", basis="tekst")
    assert event.model_dump()["kind"] == "beëdiging"
    assert event.kind is SeatEventKind.BEEDIGING
    assert event.basis is SeatEventBasis.TEKST


def test_a_derived_event_of_the_tweede_kamer_is_typed() -> None:
    seats = [
        {"member": f"m{n}", "faction_key": "vvd", "from_date": "2023-12-06"}
        for n in range(60)
    ]
    (event,) = tk_events("2023-12-06", seats, [], None, set())
    assert event["kind"] is SeatEventKind.VERKIEZING
    assert event["basis"] is SeatEventBasis.AFGELEID
    assert SeatEventDTO(**event).model_dump()["kind"] == "verkiezing"

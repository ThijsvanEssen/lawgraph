"""What begins a stretch of the seats of a Kamer (``SeatEventKind``), and how it is known
(``SeatEventBasis``): the words of the Eerste Kamer's pages, or derived from the periods of
the seats of the Tweede Kamer."""

from __future__ import annotations

from enum import StrEnum


class SeatEventKind(StrEnum):
    # the Eerste Kamer, read from its pages (``core.ek_mutations``)
    BEEDIGING = "beëdiging"
    VERTREK = "vertrek"
    OVERSTAP = "overstap"
    AFSPLITSING = "afsplitsing"
    HERNOEMING = "hernoeming"
    SAMENVOEGING = "samenvoeging"
    # the Tweede Kamer, derived from its seats (``core.coalition.tk_events``); also
    # ``afsplitsing`` and ``overstap``
    VERKIEZING = "verkiezing"
    VACATURE = "vacature"
    OPVOLGING = "opvolging"
    COALITIE = "coalitie"


class SeatEventBasis(StrEnum):
    # read from the source's words: show the words
    TEKST = "tekst"
    # derived from the periods of the seats: show the kind as a label
    AFGELEID = "afgeleid"

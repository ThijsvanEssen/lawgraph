"""The official publications of the Staat: the Staatsblad, the Staatscourant and the
Tractatenblad (pure functions, no I/O).

A publication has an id of officielebekendmakingen.nl (KOOP), ``stb-2019-33``, and is cited
by its series, year and number: ``Stb. 2019, 33``.
"""

from __future__ import annotations

import re
from typing import Literal, get_args

from lawgraph.core.models import make_node_key

PublicationSeries = Literal["stb", "stcrt", "trb"]

_ABBREVIATIONS: dict[PublicationSeries, str] = {
    "stb": "Stb.",
    "stcrt": "Stcrt.",
    "trb": "Trb.",
}
SERIES: tuple[PublicationSeries, ...] = get_args(PublicationSeries)
_SERIES: dict[str, PublicationSeries] = {s: s for s in SERIES}
_KOOP_ID = re.compile(r"^(stb|stcrt|trb)-(\d{4})-(\d+)$", re.IGNORECASE)


def publication_series(value: object) -> PublicationSeries | None:
    """``stb`` for ``Stb`` (the BWB's ``soort``) or ``stb``; None for another series."""
    return _SERIES.get(str(value or "").strip().lower())


def koop_id(series: str, year: int | str, number: int | str) -> str:
    """``stb-2019-33``: the id officielebekendmakingen.nl gives a publication."""
    return f"{series.lower()}-{year}-{number}"


def parse_koop_id(value: str) -> tuple[PublicationSeries, int, str] | None:
    """``(series, year, number)`` of ``stb-2019-33``, the number as written; None for
    another id."""
    match = _KOOP_ID.match(value.strip())
    if not match:
        return None
    return _SERIES[match[1].lower()], int(match[2]), match[3]


def publication_citation(
    series: PublicationSeries, year: int | str, number: int | str
) -> str:
    """``Stb. 2019, 33``: how a publication is cited (``stcrt-2020-00012`` as ``Stcrt.
    2020, 12``)."""
    number = str(number)
    return f"{_ABBREVIATIONS[series]} {year}, {int(number) if number.isdigit() else number}"


def koop_citation(value: str) -> str | None:
    """``Stb. 2019, 33`` for ``stb-2019-33``; None for another id."""
    parsed = parse_koop_id(value)
    return publication_citation(*parsed) if parsed else None


def instrument_key(official: str) -> str:
    """``stb_2026_94``: the key of the publication the BWB names (``stb-2026-94``)."""
    return make_node_key(official)


def official_of_instrument_key(key: str) -> str:
    """``stb-2026-94`` of the instrument key ``stb_2026_94``."""
    return key.replace("_", "-")


def note_key(official: str) -> str:
    """``stb_stb_2026_94``: the key of the nota van toelichting of ``stb-2026-94``, a
    document of its own source (the series) keyed by its id."""
    return make_node_key(official.split("-")[0], official)


def official_of_note_key(key: str) -> str:
    """``stb-2026-94`` of the note key ``stb_stb_2026_94``."""
    return official_of_instrument_key(key.partition("_")[2])

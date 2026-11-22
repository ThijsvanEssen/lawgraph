"""What a dossier list keeps."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from lawgraph.db.queries._json_sql import array_or_empty, has_length

# ``proposal``: a dossier with an ``eu_ref``; ``implementation``: one that ``implements`` an
# EU act (``semantic tk-dossier-eu``).
EuFilter = Literal["proposal", "implementation"]
_EU_PROPS: dict[str, str] = {"proposal": "eu_ref", "implementation": "implements"}


@dataclass(frozen=True)
class DossierFilters:
    """What a dossier list keeps; None keeps everything."""

    status: str | None = None  # open, closed
    outcome: str | None = None
    kinds: tuple[str, ...] | None = None
    phases: tuple[str, ...] | None = None  # the current phase is one of them
    has_phase: tuple[str, ...] | None = None
    ministry: str | None = None
    seat: str | None = None  # an office: what is attributed to it (``queries.seats``)
    initiative: bool | None = None
    number: str | None = None  # a prefix of the label: 36264, 37020-
    subject: str | None = None
    committee_slug: str | None = None
    opened_from: str | None = None
    opened_to: str | None = None
    eu: EuFilter | None = None
    celex: str | None = None  # in its ``eu_ref`` or ``implements``


def eu_conditions(filters: DossierFilters, bind: dict[str, Any]) -> list[str]:
    """The SQL conditions on ``ds`` of the EU filters of *filters*."""
    conditions = []
    if filters.eu:
        conditions.append(has_length(f"ds.props -> '{_EU_PROPS[filters.eu]}'"))
    if filters.celex:
        bind["celex"] = filters.celex
        named = " OR ".join(
            f"EXISTS (SELECT 1 FROM json_array_elements("
            f"{array_or_empty(f"ds.props -> '{prop}'")}) AS a"
            " WHERE lg_str(a -> 'celex') = %(celex)s)"
            for prop in _EU_PROPS.values()
        )
        conditions.append(f"({named})")
    return conditions

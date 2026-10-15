"""Party responses: a party as a source writes it, and the colours of the parties."""

from __future__ import annotations

from pydantic import Field

from lawgraph.api.schemas.common import StrictModel


class PartyRefDTO(StrictModel):
    """A party as the source writes it (``VVD``, ``partijloos``), and its faction."""

    short: str | None = None
    faction: str | None = Field(
        None,
        description="The faction key; null for a party the TK data has no faction of.",
    )


class ColorSourceDTO(StrictModel):
    """Where the colours of a Kamer were read."""

    url: str
    what: str
    read_on: str = Field(..., description="YYYY-MM-DD.")


class ChamberColorsDTO(StrictModel):
    """The colours a Kamer draws its factions in."""

    colors: dict[str, list[str]] = Field(
        ...,
        description="Faction to its colours (two for one drawn in stripes), by every name "
        "and alias.",
    )
    source: ColorSourceDTO


class PartyColorsResponse(StrictModel):
    """Party to hex colour, by every name and alias; and the aliases."""

    colors: dict[str, str]
    aliases: dict[str, str] = Field(
        default_factory=dict,
        description="Another name of a party (`GL-PvdA`, `CU`) -> its name in `colors`.",
    )
    chambers: dict[str, ChamberColorsDTO] = Field(
        default_factory=dict,
        description="Per Kamer the colours it draws the factions in, and where they were "
        "read: the Tweede Kamer in the legend of its seat distribution, the Eerste Kamer in "
        "Wie zit waar.",
    )

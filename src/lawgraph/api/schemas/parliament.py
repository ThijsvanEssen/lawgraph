"""Seat composition of the Tweede Kamer and the Eerste Kamer."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from lawgraph.api.schemas.committees import EkSourceDTO


class FactionSeatsDTO(BaseModel):
    """A party's seats, and where it sits in the hemicycle."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    abbreviation: str | None
    name: str | None
    seats: int
    color: str | None = Field(
        None,
        description="The colour this Kamer draws the faction in (the first of `colors`), "
        "else the party's house colour; null for none.",
    )
    colors: list[str] = Field(
        default_factory=list,
        description="Every colour this Kamer draws the faction in, as it draws them: two "
        "for a faction drawn in stripes (PRO in the Tweede Kamer); empty when it draws none "
        "the list knows.",
    )
    order: int = Field(..., description="Left-to-right position in the chamber.")


class SeatingPlanDTO(BaseModel):
    """The seating plan of the plenary hall the order is taken from."""

    model_config = ConfigDict(extra="forbid")

    title: str
    dated: str = Field(..., description="The date of the plan, YYYY-MM-DD.")
    url: str = Field(..., description="The plan (PDF) on tweedekamer.nl.")
    page: str | None = Field(None, description="The page that links it.")


class ParliamentSeatsResponse(BaseModel):
    """The seat composition of the Tweede Kamer or the Eerste Kamer."""

    model_config = ConfigDict(extra="forbid")

    chamber: Literal["TK", "EK"] = "TK"
    total_seats: int
    assigned_seats: int
    as_of: str
    factions: list[FactionSeatsDTO]
    seating_plan: SeatingPlanDTO | None = Field(
        None,
        description="The plan of the Tweede Kamer the order of `factions` follows; null "
        "for the Eerste Kamer, whose factions are in the order of their seats.",
    )
    source: EkSourceDTO | None = Field(
        None, description="Of the Eerste Kamer: the page the seats were read from."
    )


class ColorSourceDTO(BaseModel):
    """Where the colours of a Kamer were read."""

    model_config = ConfigDict(extra="forbid")

    url: str
    what: str
    read_on: str = Field(..., description="YYYY-MM-DD.")


class ChamberColorsDTO(BaseModel):
    """The colours a Kamer draws its factions in."""

    model_config = ConfigDict(extra="forbid")

    colors: dict[str, list[str]] = Field(
        ...,
        description="Faction to its colours (two for one drawn in stripes), by every name "
        "and alias.",
    )
    source: ColorSourceDTO


class PartyColorsResponse(BaseModel):
    """Party to hex colour, by every name and alias; and the aliases."""

    model_config = ConfigDict(extra="forbid")

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

"""Seat composition of the Tweede Kamer and the Eerste Kamer."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from lawgraph.api.schemas.committees import EkSourceDTO, HallSeatDTO


class FactionSeatsDTO(BaseModel):
    """A party's seats, and where it sits in the hemicycle."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    abbreviation: str | None
    name: str | None
    seats: int
    color: str | None
    order: int = Field(..., description="Left-to-right position in the chamber.")


class SeatingPlanDTO(BaseModel):
    """The seating plan of the plenary hall the order is taken from."""

    model_config = ConfigDict(extra="forbid")

    title: str
    dated: str = Field(..., description="The date of the plan, YYYY-MM-DD.")
    url: str = Field(..., description="The plan (PDF) on tweedekamer.nl.")
    page: str | None = Field(None, description="The page that links it.")


class HallPlaceDTO(HallSeatDTO):
    """A seat of the hall and who holds it."""

    faction: str = Field(..., description="The key of the faction (``ek_…``).")
    abbreviation: str | None = None
    member: str = Field(..., description="The key of the member.")
    name: str | None = Field(None, description="As the Kamer writes it.")


class HallDTO(BaseModel):
    """The plenary hall of the Eerste Kamer as Wie zit waar on eerstekamer.nl draws it."""

    model_config = ConfigDict(extra="forbid")

    url: str
    seats: list[HallPlaceDTO] = Field(
        ...,
        description="Every seat a member holds: the left block, the chair, the right "
        "block, each row by row and place by place. A place no one holds is not listed: "
        "a row has as many places as its highest column.",
    )


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
    hall: HallDTO | None = Field(
        None,
        description="Of the Eerste Kamer: who sits where in its plenary hall; null for "
        "the Tweede Kamer, and when no plan was read.",
    )


class PartyColorsResponse(BaseModel):
    """Party to hex colour, by every name and alias; and the aliases."""

    model_config = ConfigDict(extra="forbid")

    colors: dict[str, str]
    aliases: dict[str, str] = Field(
        default_factory=dict,
        description="Another name of a party (`GL-PvdA`, `CU`) -> its name in `colors`.",
    )

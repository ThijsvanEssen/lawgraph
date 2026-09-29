"""Seat composition of the Tweede Kamer."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


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


class ParliamentSeatsResponse(BaseModel):
    """The current seat composition of the Tweede Kamer."""

    model_config = ConfigDict(extra="forbid")

    total_seats: int
    assigned_seats: int
    as_of: str
    factions: list[FactionSeatsDTO]
    seating_plan: SeatingPlanDTO | None = Field(
        None,
        description="The plan of the Tweede Kamer the order of `factions` follows.",
    )


class PartyColorsResponse(BaseModel):
    """Party to hex colour, by every name and alias; and the aliases."""

    model_config = ConfigDict(extra="forbid")

    colors: dict[str, str]
    aliases: dict[str, str] = Field(
        default_factory=dict,
        description="Another name of a party (`GL-PvdA`, `CU`) -> its name in `colors`.",
    )

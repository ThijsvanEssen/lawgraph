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


class ParliamentSeatsResponse(BaseModel):
    """The current seat composition of the Tweede Kamer."""

    model_config = ConfigDict(extra="forbid")

    total_seats: int
    assigned_seats: int
    as_of: str
    factions: list[FactionSeatsDTO]


class PartyColorsResponse(BaseModel):
    """Party abbreviation to hex colour."""

    model_config = ConfigDict(extra="forbid")

    colors: dict[str, str]

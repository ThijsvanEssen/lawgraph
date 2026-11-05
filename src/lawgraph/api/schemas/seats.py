"""Office responses: a seat over the renames of its ministry, with its holders and gaps."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from lawgraph.api.params import MinistryKey, Post
from lawgraph.api.schemas.common import END_OF_OFFICE, StrictModel
from lawgraph.api.schemas.members import PersonRefDTO
from lawgraph.api.schemas.ministries import WithMinistry
from lawgraph.db.queries.seats import Attribution


class SeatHolderDTO(WithMinistry):
    """A post in the seat: one person, in one cabinet, under one name of the ministry."""

    member: PersonRefDTO
    seat: str = Field(
        ...,
        description="The seat as it was then, with its lane: ``bz/staatssecretaris#2``.",
    )
    post: Post | None = None
    function: str | None = Field(None, description="As Rijksoverheid names the post.")
    ministry: MinistryKey | None = None
    cabinet_key: str | None = None
    cabinet_name: str | None = None
    from_date: str | None = Field(None, description="The day it began.")
    to_date: str | None = Field(None, description=END_OF_OFFICE)
    acting: bool = Field(False, description="A stand-in (ad interim).")
    overlaps_with: list[str] = Field(
        default_factory=list,
        description="The members who held the same seat at the same time: a conflict in "
        "the source, not hidden.",
    )

    @classmethod
    def from_post(cls, post: dict[str, Any]) -> SeatHolderDTO:
        return cls(
            member=PersonRefDTO.from_row(post["member"]),
            cabinet_name=post.get("cabinet"),
            **{name: post.get(name) for name in _POST_FIELDS},
            acting=bool(post.get("acting")),
            overlaps_with=post.get("overlaps_with") or [],
        )


_POST_FIELDS = (
    "seat",
    "post",
    "function",
    "ministry",
    "cabinet_key",
    "from_date",
    "to_date",
)


class SeatGapDTO(StrictModel):
    """A stretch longer than two weeks between two holders: no post known, or no such office
    then. Not filled in."""

    from_date: str
    to_date: str


class SeatCountsDTO(StrictModel):
    """How much of a list can be attributed to the seat."""

    attributed: int = Field(
        ..., description="The ``total`` of the list filtered on this ``seat``."
    )
    unattributed: int = Field(
        ...,
        description="Of its ministry and kind, on a day the seat was held, but with no "
        "member found or a member who fits no one seat that day: in no list of a seat.",
    )

    @classmethod
    def of(cls, attribution: Attribution) -> SeatCountsDTO:
        return cls(
            attributed=len(attribution.ids), unattributed=attribution.unattributed
        )


class SeatDTO(StrictModel):
    """An office, over the names of its ministry."""

    seat: str = Field(
        ..., description="By its latest name: ``ienw/minister``, without a lane."
    )
    names: list[str] = Field(
        ..., description="Every name it was held under, oldest first."
    )
    merged_from: list[str] = Field(
        default_factory=list,
        description="The seats of ministries that merged into this one (``venw/minister`` "
        "into ``ienm/minister``): other offices, their holders not among these.",
    )
    merged_into: list[str] = Field(
        default_factory=list,
        description="The seat of the ministry this one merged into: another office.",
    )
    holders: list[SeatHolderDTO] = Field(..., description="Oldest first.")
    gaps: list[SeatGapDTO] = Field(default_factory=list)
    commitments: SeatCountsDTO
    dossiers: SeatCountsDTO

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> SeatDTO:
        return cls(
            seat=row["seat"],
            names=row["names"],
            merged_from=row["merged_from"],
            merged_into=row["merged_into"],
            holders=[SeatHolderDTO.from_post(post) for post in row["holders"]],
            gaps=[SeatGapDTO(**gap) for gap in row["gaps"]],
            commitments=SeatCountsDTO.of(row["commitments"]),
            dossiers=SeatCountsDTO.of(row["dossiers"]),
        )

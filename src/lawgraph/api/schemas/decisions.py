"""Decision (vote) responses."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class VoteDTO(BaseModel):
    """One vote cast on a decision, by a faction or — on a roll-call — a member."""

    model_config = ConfigDict(extra="forbid")

    voter_id: str = Field(..., description="Arango _id of the member or faction.")
    voter_key: str
    name: str | None = None
    choice: str = Field(
        ..., description="The vote as the source wrote it: Voor, Tegen, Onthouden, …"
    )
    seats: int = 0


class DecisionDTO(BaseModel):
    """One decision with every vote cast on it.

    ``vote_kind`` says who the votes come from: ``member`` for a roll-call
    (``hoofdelijke stemming``), ``faction`` otherwise. ``tally`` is seats per
    choice — members per choice on a roll-call — and ``voters`` is how many
    cast each choice.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    date: str | None = None
    subject: str | None = None
    external_id: str | None = Field(None, description="TK Besluit identifier.")
    passed: bool
    chamber: str | None = None
    vote_kind: str = "faction"
    tally: dict[str, int] = Field(default_factory=dict)
    voters: dict[str, int] = Field(default_factory=dict)
    votes: list[VoteDTO] = Field(default_factory=list)

    @classmethod
    def from_document(cls, doc: dict[str, Any]) -> DecisionDTO:
        props = doc.get("props") or {}
        return cls(
            id=doc["_id"],
            key=doc["_key"],
            date=props.get("date"),
            subject=props.get("subject"),
            external_id=props.get("decision_id"),
            passed=bool(props.get("passed")),
            chamber=props.get("chamber"),
            vote_kind=props.get("vote_kind") or "faction",
            tally=props.get("tally") or {},
            voters=props.get("voters") or {},
            votes=[VoteDTO(**v) for v in doc.get("votes") or []],
        )


class DecisionSummaryDTO(BaseModel):
    """One row in the decision browser.

    ``tally`` sums the seats behind each choice — the number to show for a
    result — and ``voters`` counts how many factions (or members) made it.
    ``external_id`` identifies the motion within a debate; use it rather than
    ``subject``, which is shared by every motion on the same agenda item.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    date: str | None = None
    subject: str | None = None
    external_id: str | None = None
    dossier_numbers: list[str] = Field(default_factory=list)
    passed: bool | None = None
    chamber: str | None = None
    vote_kind: str | None = None
    tally: dict[str, int] = Field(default_factory=dict)
    voters: dict[str, int] = Field(default_factory=dict)


class DecisionListResponse(BaseModel):
    """A page of decisions."""

    model_config = ConfigDict(extra="forbid")

    total: int = Field(..., description="Matching decisions, independent of ``limit``.")
    items: list[DecisionSummaryDTO]

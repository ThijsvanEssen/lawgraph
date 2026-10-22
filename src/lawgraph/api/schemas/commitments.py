"""Commitment responses."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from lawgraph.api.params import MinistryKey, Post
from lawgraph.api.schemas.common import (
    FacetCountDTO,
    PathSource,
    StrictModel,
    WithKindGroup,
    WithPath,
)
from lawgraph.api.schemas.members import PersonRefDTO
from lawgraph.core.dossier_numbers import short_title
from lawgraph.core.tk_records.commitments import due_date

# Why a commitment is about a dossier: ``meta.basis`` of its ``ABOUT`` edge.
CommitmentBasis = Literal["nakoming", "agenda"]

# The status of a commitment is the Toezegging.Status the Tweede Kamer gives it.
COMMITMENT_STATUS_DESCRIPTION = (
    "The status the Tweede Kamer gives the commitment (`Toezegging.Status`), as it writes "
    "it: `Openstaand`, `Afgedaan`, `Nagekomen`, `Niet nagekomen`, `Deels Afgedaan`, "
    "`Vervallen`; null when it gives none."
)


class CommitmentDossierDTO(WithPath):
    path_source = PathSource("dossiers")

    key: str
    number: str | None = None
    title: str | None = None
    short_title: str | None = Field(
        None, description="The name it goes by, as ``/api/dossiers`` gives it."
    )
    basis: CommitmentBasis | None = Field(
        None,
        description="Why it is this dossier: `nakoming`, the dossier of a letter that "
        "fulfils it (`Toezegging.KamerbriefNakoming`); `agenda`, a dossier on the agenda of "
        "the debate it was made in, where it was discussed (a commitment no letter in a "
        "dossier fulfils yet).",
    )


class CommitmentActivityDTO(WithPath):
    """The activity a commitment was made in: a debate, as the Kamer names it."""

    path_source = PathSource("activities")

    key: str
    date: str | None = Field(None, description="The day it was held.")
    number: str | None = None
    kind: str | None = Field(
        None, description="As the source writes it: ``Wetgevingsoverleg``."
    )
    agenda_title: str | None = Field(
        None, description="Its subject (``Activiteit.Onderwerp``)."
    )


class CommitmentLetterDTO(WithKindGroup, WithPath):
    """A letter that fulfils a commitment (``Toezegging.KamerbriefNakoming``)."""

    path_source = PathSource("documents")

    id: str
    key: str
    kind: str | None = None
    date: str | None = None
    title: str | None = None
    dossier_number: str | None = None
    dossier_suffix: str | None = None
    sequence: int | None = Field(
        None, description="Its number in its dossier (nr. 33)."
    )


class CommitmentMemberDTO(PersonRefDTO):
    """Who made the commitment, and the role they made it in as the source writes it."""

    function: str | None = None


class CommitmentDTO(WithPath):
    """A commitment (toezegging) of a bewindspersoon to the Tweede Kamer."""

    path_source = PathSource("commitments")

    key: str
    number: str | None = Field(
        None, description="How the Kamer cites it: `TZ202603-130`."
    )
    text: str | None = None
    status: str | None = Field(None, description=COMMITMENT_STATUS_DESCRIPTION)
    date: str | None = Field(
        None,
        description="The day it was made: that of the activity it was made in (the "
        "debate), else ``registered_on``.",
    )
    registered_on: str | None = Field(
        None,
        description="The day the Kamer registered it (``Aanmaakdatum``), often weeks "
        "after the debate.",
    )
    expected_resolution: str | None = Field(
        None, description="The day it is due; null when the Kamer names none."
    )
    minister_name: str | None = Field(None, description="As the source writes it.")
    member: CommitmentMemberDTO | None = Field(
        None, description="The member who made it; null when no member fits the name."
    )
    post: Post | None = None
    ministry: MinistryKey | None = None
    cabinet: str | None = Field(None, description="The cabinet in office that day.")
    dossiers: list[CommitmentDossierDTO] = Field(default_factory=list)
    activity: CommitmentActivityDTO | None = Field(
        None, description="The activity it was made in (``MADE_IN``)."
    )
    fulfilled_by: list[CommitmentLetterDTO] = Field(
        default_factory=list,
        description="The letters that fulfil it (``ANSWERS``, from "
        "``Toezegging.KamerbriefNakoming``), oldest first.",
    )

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> CommitmentDTO:
        """From a row of ``get_commitments``."""
        commitment = row["commitment"]
        props = commitment.get("props") or {}
        member = row.get("member")
        due = props.get("expected_resolution")
        made_in = row.get("activity")
        activity = CommitmentActivityDTO(**made_in) if made_in else None
        return cls(
            key=commitment["key"],
            number=props.get("number"),
            text=props.get("text"),
            status=props.get("status"),
            date=props.get("made_on"),
            registered_on=props.get("registered_on"),
            expected_resolution=due_date(due),
            minister_name=props.get("minister_name"),
            member=(
                CommitmentMemberDTO.from_row(
                    member, function=props.get("minister_role")
                )
                if member
                else None
            ),
            post=props.get("post"),
            ministry=props.get("ministry"),
            cabinet=props.get("cabinet"),
            dossiers=[
                CommitmentDossierDTO(**d, short_title=short_title(d.get("title")))
                for d in row.get("dossiers") or []
            ],
            activity=activity,
            fulfilled_by=[
                CommitmentLetterDTO(
                    **{
                        **letter,
                        "sequence": (
                            letter.get("sequence")
                            if isinstance(letter.get("sequence"), int)
                            else None
                        ),
                    }
                )
                for letter in row.get("fulfilled_by") or []
            ],
        )


class CommitmentFacetsDTO(StrictModel):
    """Per dimension the number of commitments per value under the current filters, each
    dimension counted without its own filter, the largest first: only the values that
    have commitments (a ministry without any is not listed)."""

    status: list[FacetCountDTO] = Field(default_factory=list)
    cabinet: list[FacetCountDTO] = Field(default_factory=list)
    ministry: list[FacetCountDTO] = Field(default_factory=list)


class CommitmentListResponse(StrictModel):
    total: int = Field(..., description="Matching commitments, whatever the page.")
    items: list[CommitmentDTO]
    # null when asked for without them (``facets=false``)
    facets: CommitmentFacetsDTO | None = Field(default_factory=CommitmentFacetsDTO)

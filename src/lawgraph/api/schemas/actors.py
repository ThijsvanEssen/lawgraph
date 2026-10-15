"""What a member and a faction answer alike: the laws they change most and the dossiers they
authored in."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from lawgraph.api.schemas.common import StrictModel
from lawgraph.api.schemas.dossiers import DossierSummaryDTO
from lawgraph.core.tk_records.actors import SigningCapacity


class TouchedInstrumentDTO(StrictModel):
    """One law an actor proposes changes to, with how often they do."""

    id: str = Field(..., description="Node id (``collection/key``) of the instrument.")
    key: str
    display_name: str | None = None
    title: str | None = None
    short_title: str | None = None
    citation_title: str | None = None
    bwb_id: str | None = None
    celex: str | None = None
    count: int = Field(
        ..., description="Distinct documents by this actor that change the law."
    )


class TouchedInstrumentsResponse(StrictModel):
    """Wrapper for an actor's touched-instruments list."""

    actor_id: str = Field(
        ..., description="Node id (``collection/key``) of the member or faction."
    )
    count: int = Field(
        ..., description="Instruments returned; may be fewer than the total."
    )
    items: list[TouchedInstrumentDTO]


class ActorDossierDTO(DossierSummaryDTO):
    """A dossier a member or faction authored documents in.

    ``roles`` are the distinct ``AUTHORED`` roles as the source wrote them
    (``Eerste ondertekenaar``, ``Mede ondertekenaar``, ...); ``functions`` and ``capacities``
    what they signed as, which changes over time (a Kamerlid who became minister-president);
    ``document_count`` the distinct documents authored in the dossier.
    """

    roles: list[str] = Field(default_factory=list)
    functions: list[str] = Field(
        default_factory=list,
        description="The distinct functions signed in, as the source writes them "
        "('Tweede Kamerlid', 'minister-president').",
    )
    capacities: list[SigningCapacity] = Field(
        default_factory=list,
        description="The distinct capacities signed in: 'kamerlid', 'bewindspersoon', "
        "'overig'.",
    )
    document_count: int = 0

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> ActorDossierDTO:
        return cls(
            **DossierSummaryDTO.fields_of(row["dossier"]),
            roles=list(row.get("roles") or []),
            functions=list(row.get("functions") or []),
            capacities=list(row.get("capacities") or []),
            document_count=int(row.get("document_count") or 0),
        )


class ActorDossiersResponse(StrictModel):
    """A page of the dossiers a member or faction authored documents in."""

    actor_id: str = Field(
        ..., description="Node id (``collection/key``) of the member or faction."
    )
    total: int = Field(..., description="Dossiers, independent of limit and offset.")
    items: list[ActorDossierDTO]

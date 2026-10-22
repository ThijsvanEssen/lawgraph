"""Committee responses."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from lawgraph.api.schemas.common import (
    DossierNameDTO,
    PathSource,
    StrictModel,
    WithPath,
)
from lawgraph.api.schemas.dossiers import DossierSummaryDTO
from lawgraph.api.schemas.ek_source import (
    OBSERVED_FROM,
    OBSERVED_UNTIL,
    EkSourceDTO,
    ek_source,
)
from lawgraph.api.schemas.members import MemberDTO
from lawgraph.config.constants import Chamber
from lawgraph.core.tk_records.committees import CommitteeKind


def _committee_fields(doc: dict[str, Any]) -> dict[str, Any]:
    props = doc.get("props") or {}
    return {
        "chamber": props.get("chamber") or "TK",
        "observed_from": props.get("observed_from"),
        "observed_until": props.get("observed_until"),
        "source": ek_source(props),
        "id": doc["id"],
        "key": doc["key"],
        "name": props.get("name"),
        "abbreviation": props.get("abbreviation"),
        "slug": props.get("slug"),
        "kind": props.get("kind"),
        "started_on": props.get("started_on"),
        "ended_on": props.get("ended_on"),
        "active_dossier_count": int(props.get("active_dossier_count") or 0),
    }


class CommitteeDTO(WithPath):
    """A parliamentary committee."""

    path_source = PathSource("committees")

    id: str
    key: str
    chamber: Chamber = "TK"
    name: str | None = None
    abbreviation: str | None = None
    observed_from: str | None = Field(None, description=OBSERVED_FROM)
    observed_until: str | None = Field(None, description=OBSERVED_UNTIL)
    source: EkSourceDTO | None = Field(
        None, description="Of the Eerste Kamer: the page it was read from."
    )
    slug: str | None = Field(
        None,
        description="Its own: of committees that share an abbreviation the one sitting "
        "now (else the one that ended last) has it bare, the others with the year they "
        "started, `ez-2010`.",
    )
    kind: CommitteeKind | None = Field(
        None,
        description="`vast`, `algemeen`, `tijdelijk`, `enquete` (enquête or "
        "ondervraging), `delegatie` (contact groups and international assemblies) or "
        "`overig`.",
    )
    started_on: str | None = None
    ended_on: str | None = Field(None, description="Null while it sits.")
    active_dossier_count: int = Field(
        0,
        description="The open dossiers it leads (its activities are about them, its "
        "cases part of them): of a sitting committee ``dossier_total`` under "
        "``status=open``; none once ended.",
    )

    @classmethod
    def from_document(cls, doc: dict[str, Any]) -> CommitteeDTO:
        return cls(**_committee_fields(doc))


class CommitteeDetailDTO(CommitteeDTO):
    """A committee with its members and a page of the dossiers it leads.

    ``dossiers`` is one page; ``dossier_total`` counts every dossier that matches the
    ``status`` filter.
    """

    members: list[MemberDTO] | None = Field(
        None,
        description="Null when the data has no seat on it at all (not known, not "
        "none); empty when no seat is current (``current_only``).",
    )
    dossiers: list[DossierSummaryDTO] = []
    dossier_total: int = Field(
        0, description="Dossiers matching ``status``, independent of limit and offset."
    )

    @classmethod
    def from_detail_document(cls, doc: dict[str, Any]) -> CommitteeDetailDTO:
        return cls(
            **_committee_fields(doc),
            members=None
            if doc.get("members") is None
            else [MemberDTO.from_document(m) for m in doc["members"]],
            dossiers=[
                DossierSummaryDTO.from_document(d) for d in doc.get("dossiers") or []
            ],
            dossier_total=int(doc.get("dossier_total") or 0),
        )


class CommitteeActivityDTO(StrictModel):
    """One activity (debate, hearing) a committee leads."""

    id: str
    key: str
    date: str | None = Field(None, description="YYYY-MM-DD.")
    kind: str | None = Field(
        None, description="The source's ``Soort``, e.g. Commissiedebat."
    )
    agenda_title: str | None = Field(
        None, description="The subject of the activity (``Activiteit.Onderwerp``)."
    )
    status: str | None = Field(
        None,
        description="``Activiteit.Status``: ``Gepland``, ``Uitgevoerd``, ``Geannuleerd``, "
        "``Verplaatst``, ``Vervallen``.",
    )
    dossier_numbers: list[str] = Field(
        default_factory=list, description="Dossiers on the agenda of the activity."
    )
    dossiers: list[DossierNameDTO] = Field(
        default_factory=list,
        description="The names of ``dossier_numbers``, in their order: ``number``, "
        "``short_title``, ``title`` as ``/api/dossiers`` gives them.",
    )


class CommitteeActivitiesResponse(StrictModel):
    """A page of a committee's activities, newest first."""

    total: int = Field(
        ..., description="Activities of the committee, independent of limit and offset."
    )
    items: list[CommitteeActivityDTO]

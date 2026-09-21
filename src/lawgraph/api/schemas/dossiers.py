"""Dossier responses: lists, details, documents, timeline and mutations."""

from __future__ import annotations

from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

# Stage names are the Dutch legislative vocabulary the classifier speaks.
DossierStage = Literal[
    "wetsvoorstel",
    "mvt",
    "advies_rvs",
    "nota",
    "verslag",
    "amendementen",
    "stemming",
    "afgehandeld",
]

TitleSource = Literal["dossier", "document", "activiteit"]

DossierTrack = Literal[
    "wetsvoorstel",
    "initiatiefwetsvoorstel",
    "begroting",
    "motie",
    "overig",
]


def _stage(value: Any) -> DossierStage | None:
    """A recognised stage, or null when the classifier found none."""
    return value if value in get_args(DossierStage) else None


def _stages(values: Any) -> list[DossierStage]:
    valid = get_args(DossierStage)
    return [v for v in (values or []) if v in valid]


class TimelineEntryDTO(BaseModel):
    """One entry in a dossier timeline; ``body`` depends on ``kind``."""

    model_config = ConfigDict(extra="forbid")

    date: str | None
    kind: str
    title: str | None
    node_id: str
    node_type: str
    tk_url: str | None = None
    body: dict[str, Any] = Field(default_factory=dict)


class DossierDocumentDTO(BaseModel):
    """One document linked to a dossier."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    kind: str | None = None
    title: str | None = None
    sequence: int | None = Field(
        None, description="Document number within the dossier."
    )
    session_year: str | None = Field(None, description="Parliamentary year.")
    date: str | None = None
    tk_url: str | None = None
    display_name: str | None = None


class DossierDocumentsResponse(BaseModel):
    """Response for GET /api/dossiers/{number}/documents."""

    model_config = ConfigDict(extra="forbid")

    total: int = Field(
        ..., description="Documents in the dossier, independent of ``limit``."
    )
    items: list[DossierDocumentDTO]


class DossierDocumentsBulkResponse(BaseModel):
    """Response for GET /api/dossiers/documents/bulk."""

    model_config = ConfigDict(extra="forbid")

    items: dict[str, list[DossierDocumentDTO]] = Field(
        ...,
        description=(
            "Map keyed by dossier number; each value is that dossier's "
            "documents, most recent first."
        ),
    )


class DossierSummaryDTO(BaseModel):
    """A dossier in a list.

    ``track`` is what kind of dossier this is — wetsvoorstel, begroting,
    motie — and does not change as it progresses. ``current_stage`` is the
    latest stage seen on its documents and activities; ``stages`` lists every
    stage with at least one signal, in chronological order.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    number: str = Field(..., description="Kamerstuknummer, e.g. 36558.")
    title: str | None = None
    title_source: TitleSource | None = None
    track: DossierTrack | None = None
    current_stage: DossierStage | None = None
    stages: list[DossierStage] = Field(default_factory=list)
    closed: bool = False
    opened_on: str | None = None
    closed_on: str | None = None

    @classmethod
    def from_document(cls, doc: dict[str, Any]) -> DossierSummaryDTO:
        return cls(**_dossier_fields(doc))


class DossierListResponse(BaseModel):
    """A page of dossiers."""

    model_config = ConfigDict(extra="forbid")

    total: int = Field(
        ..., description="Matching dossiers, independent of limit and offset."
    )
    items: list[DossierSummaryDTO]


DossierInstrumentRelation = Literal["legislated_in", "amends", "introduces", "repeals"]
DossierInstrumentStatus = Literal["canoniek", "voorgesteld"]


class DossierInstrumentDTO(BaseModel):
    """An instrument a dossier is tied to, and how.

    ``relation`` is ``legislated_in`` (the instrument came out of this dossier) or
    ``amends``, ``introduces``, ``repeals`` (the dossier changes it, resolved from the
    article or instrument that is changed to the parent instrument). ``status`` is
    ``canoniek`` for what an amending publication enacted and ``voorgesteld`` for what a
    bill of the dossier proposes. An instrument with several relations or statuses
    appears once per combination.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    bwb_id: str | None = None
    celex: str | None = Field(None, description="Set on EU instruments.")
    display_name: str | None = None
    jurisdiction: str | None = Field(None, description="``nl`` or ``eu``.")
    relation: DossierInstrumentRelation
    status: DossierInstrumentStatus


class DossierCommitteeDTO(BaseModel):
    """A committee that leads an activity about a dossier."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    slug: str | None = None
    name: str | None = None
    abbreviation: str | None = None
    role: Literal["lead"] = "lead"


class DossierSenateDTO(BaseModel):
    """The Eerste Kamer papers among a dossier's documents."""

    model_config = ConfigDict(extra="forbid")

    document_count: int = 0
    first_date: str | None = Field(
        default=None, description="Date of the earliest paper (YYYY-MM-DD)."
    )


class DossierDetailResponse(DossierSummaryDTO):
    """A dossier with the size of everything attached to it, and what it links to."""

    model_config = ConfigDict(extra="forbid")

    document_count: int = 0
    activity_count: int = 0
    decision_count: int = 0
    commitment_count: int = 0
    instruments: list[DossierInstrumentDTO] = Field(
        default_factory=list,
        description=(
            "Instruments legislated in, amended, introduced or repealed by the "
            "dossier, one item per instrument, relation and status."
        ),
    )
    committees: list[DossierCommitteeDTO] = Field(
        default_factory=list,
        description="Committees leading an activity about the dossier.",
    )
    documents_by_kind: dict[str, int] = Field(
        default_factory=dict,
        description=(
            "Documents per kind (``Motie``, ``Amendement``, ...); a document "
            "without a kind is not counted."
        ),
    )
    senate: DossierSenateDTO = Field(default_factory=lambda: DossierSenateDTO())

    @classmethod
    def from_document(
        cls,
        doc: dict[str, Any],
        *,
        counts: dict[str, int] | None = None,
        hub: dict[str, Any] | None = None,
    ) -> DossierDetailResponse:
        counts = counts or {}
        hub = hub or {}
        return cls(
            **_dossier_fields(doc),
            document_count=counts.get("documents", 0),
            activity_count=counts.get("activities", 0),
            decision_count=counts.get("decisions", 0),
            commitment_count=counts.get("commitments", 0),
            instruments=[
                DossierInstrumentDTO(**i) for i in hub.get("instruments") or []
            ],
            committees=[DossierCommitteeDTO(**c) for c in hub.get("committees") or []],
            documents_by_kind=dict(hub.get("documents_by_kind") or {}),
            senate=DossierSenateDTO(**(hub.get("senate") or {})),
        )


def _dossier_fields(doc: dict[str, Any]) -> dict[str, Any]:
    props = doc.get("props") or {}
    return {
        "id": doc["_id"],
        "key": doc["_key"],
        "number": props.get("number") or "",
        "title": props.get("title"),
        "title_source": props.get("title_source"),
        "track": props.get("track_kind") or "overig",
        "current_stage": _stage(props.get("current_stage")),
        "stages": _stages(props.get("stages_present")),
        "closed": bool(props.get("closed")),
        "opened_on": props.get("opened_on"),
        "closed_on": props.get("closed_on"),
    }


class DossierTimelineResponse(BaseModel):
    """Everything that happened in a dossier, in date order."""

    model_config = ConfigDict(extra="forbid")

    number: str
    total: int
    order: str
    entries: list[TimelineEntryDTO]


DossierMutationKind = Literal["mutation", "explanation"]


class DossierMutationNode(BaseModel):
    """A node in the pending-change subgraph."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    collection: str
    type: str
    display_name: str | None
    labels: list[str]
    kind: DossierMutationKind

    @classmethod
    def from_document(cls, doc: dict[str, Any]) -> DossierMutationNode:
        node_id = doc.get("_id", "")
        return cls(
            id=node_id,
            key=doc.get("_key", ""),
            collection=node_id.split("/")[0] if "/" in node_id else "",
            type=doc.get("type", ""),
            display_name=(doc.get("props") or {}).get("display_name"),
            labels=list(doc.get("labels") or []),
            kind=doc.get("_kind", "mutation"),
        )


class DossierMutationEdge(BaseModel):
    """An edge in the pending-change subgraph."""

    model_config = ConfigDict(extra="forbid")

    from_id: str | None
    to_id: str | None
    relation: str | None
    status: str | None
    meta: dict[str, Any] | None = None
    kind: DossierMutationKind


class DossierMutationsResponse(BaseModel):
    """The pending-change subgraph of a dossier, shaped like the graph endpoint."""

    model_config = ConfigDict(extra="forbid")

    number: str
    nodes: list[DossierMutationNode]
    edges: list[DossierMutationEdge]

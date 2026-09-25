"""Dossier responses: lists, details, documents, timeline and mutations."""

from __future__ import annotations

from typing import Annotated, Any, Literal, cast, get_args

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from lawgraph.api.params import MinistryKey
from lawgraph.api.schemas.common import FacetCountDTO
from lawgraph.api.schemas.documents import DocumentOrigin, origin_fields
from lawgraph.core.dossier_numbers import short_title
from lawgraph.core.tk_links import tk_url

# A dossier number as the API takes it: 29684, or its label with the addition of a
# budget chapter or a sub-series: 29684-I, 21501-31, 36956-(R2220).
DOSSIER_NUMBER_PATTERN = r"^\d+(-[A-Za-z0-9()]+)?$"

# Stage names are the Dutch legislative vocabulary the classifier speaks.
DossierStage = Literal[
    "wetsvoorstel",
    "mvt",
    "advies_rvs",
    "verslag",
    "nota_naar_aanleiding_van_verslag",
    "amendementen",
    "behandeling",
    "stemming",
    "afgehandeld",
]

TitleSource = Literal["dossier", "document", "activiteit"]

SigningCapacity = Literal["kamerlid", "bewindspersoon", "overig"]

DossierOutcome = Literal["aangenomen", "verworpen", "ingetrokken"]

DossierTrack = Literal[
    "wetsvoorstel",
    "initiatiefwetsvoorstel",
    "begroting",
    "verdrag",
    "initiatiefnota",
    "nota",
    "overig",
]


def _stage(value: Any) -> DossierStage | None:
    """A recognised stage, or null when the classifier found none."""
    return value if value in get_args(DossierStage) else None


def _stages(values: Any) -> list[DossierStage]:
    valid = get_args(DossierStage)
    return [v for v in (values or []) if v in valid]


class TimelineCommitteeDTO(BaseModel):
    """The committee that leads an activity."""

    model_config = ConfigDict(extra="forbid")

    key: str
    slug: str | None = None
    name: str | None = None


class TimelineSignatoryDTO(BaseModel):
    """Who signed the document a decision was taken on."""

    model_config = ConfigDict(extra="forbid")

    member_key: str | None = None
    name: str | None = None
    party: str | None = None
    role: str = Field(..., description="'indiener' or 'mede-indiener'.")
    source_role: str = Field("", description="The role as the source wrote it.")
    function: str | None = Field(
        None,
        description="The function they signed in, as the source writes it: 'Tweede "
        "Kamerlid', 'minister-president', 'vicepresident van de Raad van State'.",
    )
    capacity: SigningCapacity | None = Field(
        None,
        description="'bewindspersoon' (a minister or staatssecretaris), 'kamerlid' (signed "
        "for a faction) or 'overig' (the griffier, the Raad van State, ...).",
    )


class DocumentEntryDTO(DocumentOrigin):
    """A document as it is named from another node: identity and paper number, never text."""

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


class TimelineDocumentSummaryDTO(DocumentEntryDTO):
    """The document a decision was taken on: what it says and who signed it."""

    dictum_excerpt: str | None = Field(
        None, description="The first 280 characters of the document's text."
    )
    signatories: list[TimelineSignatoryDTO] = Field(default_factory=list)


class TimelineDocumentBody(DocumentOrigin):
    """A document entry: what identifies the document, never its text.

    Fetch ``/api/documents/{key}`` for the text. ``url`` is the page of an Eerste
    Kamer paper on officielebekendmakingen.nl; ``tk_url`` the paper on tweedekamer.nl.
    """

    kind: str | None = None
    title: str | None = None
    sequence: int | None = Field(
        None, description="Document number within the dossier."
    )
    session_year: str | None = Field(None, description="Parliamentary year.")
    tk_url: str | None = None
    url: str | None = None


class TimelineActivityBody(BaseModel):
    """An activity entry: a debate, hearing or other agenda item."""

    model_config = ConfigDict(extra="forbid")

    kind: str | None = Field(None, description="E.g. 'Commissiedebat'.")
    agenda_title: str | None = Field(
        None, description="The subject of the activity (``Activiteit.Onderwerp``)."
    )
    number: str | None = Field(None, description="The activity number.")
    status: str | None = Field(
        None,
        description="``Activiteit.Status`` as the source writes it: ``Gepland`` (still to "
        "come, also when its date has passed), ``Uitgevoerd``, ``Geannuleerd``, "
        "``Verplaatst``, ``Vervallen``; null when the source gives none.",
    )


class TimelineDecisionBody(BaseModel):
    """A decision entry: the vote, and the document it was taken on.

    ``tally`` is seats per choice and ``voters`` how many factions (or members)
    cast each. ``document`` is the motion or amendment decided on, when it can be
    resolved.
    """

    model_config = ConfigDict(extra="forbid")

    subject: str | None = None
    passed: bool | None = None
    vote_kind: str | None = None
    tally: dict[str, int] = Field(default_factory=dict)
    voters: dict[str, int] = Field(default_factory=dict)
    external_id: str | None = Field(None, description="TK Besluit identifier.")
    primary_case_kind: str | None = Field(
        None,
        description="The ``Zaak.Soort`` of the case it decided: ``Wetgeving`` on the vote on "
        "a bill itself, ``Amendement`` or ``Motie`` on the others.",
    )
    document: TimelineDocumentSummaryDTO | None = None


class TimelineCommitmentBody(BaseModel):
    """A commitment (toezegging) entry."""

    model_config = ConfigDict(extra="forbid")

    text: str | None = None
    minister_name: str | None = None
    minister_role: str | None = None
    status: str | None = Field(None, description="'open', 'done' or 'vervallen'.")
    expected_resolution: str | None = None


class _TimelineEntry(BaseModel):
    """What every timeline entry has; the body and ``node_type`` say the rest."""

    model_config = ConfigDict(extra="forbid")

    date: str | None
    kind: str
    title: str | None
    node_id: str
    tk_url: str | None = None
    after_closure: bool = Field(
        False,
        description="Dated after the dossier's ``closed_on``: a follow-up letter, a debate "
        "or procedure meeting after the law was published. False for an open dossier.",
    )
    planned: bool = Field(
        False,
        description="An activity with ``status`` ``Gepland``: announced, not (yet) held.",
    )


class TimelineDocumentEntry(_TimelineEntry):
    """A document that is PART_OF the dossier."""

    node_type: Literal["document"]
    body: TimelineDocumentBody


class TimelineActivityEntry(_TimelineEntry):
    """An activity ABOUT the dossier; ``committee`` is null for a plenary one."""

    node_type: Literal["activity"]
    body: TimelineActivityBody
    committee: TimelineCommitteeDTO | None = None


class TimelineDecisionEntry(_TimelineEntry):
    """A decision ABOUT the dossier."""

    node_type: Literal["decision"]
    body: TimelineDecisionBody


class TimelineCommitmentEntry(_TimelineEntry):
    """A commitment ABOUT the dossier."""

    node_type: Literal["commitment"]
    body: TimelineCommitmentBody


TimelineEntryDTO = Annotated[
    TimelineDocumentEntry
    | TimelineActivityEntry
    | TimelineDecisionEntry
    | TimelineCommitmentEntry,
    Field(discriminator="node_type"),
]
_TIMELINE_ENTRY: TypeAdapter[TimelineEntryDTO] = TypeAdapter(TimelineEntryDTO)


def timeline_entry(row: dict[str, Any]) -> TimelineEntryDTO:
    """The typed entry for one timeline row of ``get_dossier_timeline``."""
    body = row.get("body") or {}
    node_type = row.get("node_type")
    link = tk_url(node_type, body)
    common = {
        "date": row.get("date"),
        "kind": row.get("kind") or "",
        "title": row.get("title"),
        "node_id": row.get("node_id") or "",
        "tk_url": link,
        "node_type": node_type,
        "after_closure": bool(row.get("after_closure")),
        "planned": bool(row.get("planned")),
    }
    if node_type == "document":
        common["body"] = {
            **{f: body.get(f) for f in ("kind", "title", "sequence", "session_year")},
            "tk_url": link,
            "url": body.get("url"),
            **origin_fields(row.get("labels"), body.get("source"), body.get("kind")),
        }
    elif node_type == "decision":
        common["body"] = {
            "subject": body.get("subject"),
            "passed": body.get("passed"),
            "vote_kind": body.get("vote_kind"),
            "tally": body.get("tally") or {},
            "voters": body.get("voters") or {},
            "external_id": body.get("decision_id"),
            "primary_case_kind": body.get("primary_case_kind"),
            "document": body.get("document"),
        }
    else:
        common["body"] = body
    if node_type == "activity":
        common["committee"] = row.get("committee")
    return _TIMELINE_ENTRY.validate_python(common)


class DossierDocumentDTO(DocumentEntryDTO):
    """One document linked to a dossier."""

    display_name: str | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> DossierDocumentDTO:
        """From a document row of ``get_dossier_documents``."""
        return cls(
            id=row["id"],
            key=row["key"],
            kind=row.get("kind"),
            title=row.get("title"),
            sequence=row.get("sequence"),
            session_year=row.get("session_year"),
            date=row.get("date"),
            tk_url=tk_url("document", row),
            display_name=row.get("display_name"),
            **origin_fields(row.get("labels"), row.get("source"), row.get("kind")),
        )


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

    ``track`` is what kind of dossier this is — a bill (wetsvoorstel,
    initiatiefwetsvoorstel, begroting, verdrag), an initiatiefnota, a ``nota`` of the
    government (the Miljoenennota, the Voorjaars- and Najaarsnota, the Financieel
    Jaarverslag van het Rijk) or ``overig`` (the letters and motions on a subject) — and
    does not change as it progresses. It comes from what the dossier is, never from what
    is filed under it. ``current_stage`` is the
    latest stage seen on its documents and activities; ``stages`` lists every
    stage with at least one signal, in chronological order. Only a bill (a
    wetsvoorstel, initiatiefwetsvoorstel, begroting or verdrag) passes stages;
    any other dossier has none until it is ``afgehandeld``. A closed dossier has
    an ``outcome``: ``aangenomen`` (its law was published), ``ingetrokken`` (its
    bill was withdrawn) or ``verworpen`` (the Tweede Kamer voted the bill down).
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    number: str = Field(
        ...,
        description="Kamerstuknummer, e.g. 36558, or 37020-XV for a budget chapter.",
    )
    suffix: str | None = Field(
        None,
        description="The addition to the number (``Toevoeging``): ``XV`` of 37020-XV, "
        "``31`` of 21501-31; null for a dossier without one.",
    )
    same_number_count: int = Field(
        0,
        description="How many other dossiers share the number: 24 for each dossier of a "
        "budget of 25. ``GET /api/dossiers?number=`` lists them.",
    )
    title: str | None = None
    short_title: str | None = Field(
        None,
        description="The name a bill goes by, from the parentheses that end its title: "
        "``Verzamelwet gegevensbescherming``; null when the title has none.",
    )
    title_source: TitleSource | None = None
    track: DossierTrack | None = None
    current_stage: DossierStage | None = None
    stages: list[DossierStage] = Field(default_factory=list)
    stages_complete: bool = Field(
        True,
        description="Whether every stage the bill passed on its way to "
        "``current_stage`` has a document, an activity or a vote in the graph: the stages "
        "in ``stages`` before it and ``current_stage`` itself, and those every bill of its "
        "track passes (``wetsvoorstel``, ``mvt`` and ``advies_rvs`` of a bill; "
        "``wetsvoorstel`` and ``mvt`` of a budget; ``advies_rvs`` of a treaty; and "
        "``stemming`` once a bill or budget was aangenomen or verworpen; an ``Eindtekst`` "
        "counts as the vote). False means the graph lacks papers of the dossier: a stage between "
        "two listed ones was passed but is not in the data. True for a dossier that is no "
        "bill. ``stages_missing`` names the stages.",
    )
    stages_missing: list[DossierStage] = Field(
        default_factory=list,
        description="The stages the bill passed without a dated document, activity or vote "
        "in the graph, in stage order: ``stemming`` on a law published without a vote on "
        "record. Empty when ``stages_complete``.",
    )
    closed: bool = False
    outcome: DossierOutcome | None = None
    opened_on: str | None = None
    closed_on: str | None = None
    ministry: MinistryKey | None = Field(
        None,
        description="The ministry (``GET /api/ministries``) of the bewindspersoon who "
        "signed the earliest signed document of the dossier first; null for an initiative "
        "or when nobody in government or parliament signed first.",
    )
    initiative: bool | None = Field(
        None,
        description="True when a Kamerlid signed the earliest signed document first, false "
        "when a bewindspersoon did, null when neither did.",
    )
    cabinet: str | None = Field(
        None,
        description="The key of the cabinet in office when that document was signed.",
    )

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
    facets: DossierFacetsDTO


class DossierFacetsDTO(BaseModel):
    """Per dimension the number of dossiers per value under the current filters, each
    dimension counted without its own filter (so the other values of a chosen dimension
    keep their counts), the largest first."""

    model_config = ConfigDict(extra="forbid")

    status: list[FacetCountDTO] = Field(default_factory=list)
    outcome: list[FacetCountDTO] = Field(default_factory=list)
    track: list[FacetCountDTO] = Field(default_factory=list)
    stage: list[FacetCountDTO] = Field(default_factory=list)
    ministry: list[FacetCountDTO] = Field(default_factory=list)


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


class DossierCommitteeDTO(TimelineCommitteeDTO):
    """A committee that leads an activity about a dossier."""

    id: str
    abbreviation: str | None = None
    role: Literal["lead"] = "lead"


class DossierSenateDTO(BaseModel):
    """The Eerste Kamer papers among a dossier's documents."""

    model_config = ConfigDict(extra="forbid")

    document_count: int = 0
    first_date: str | None = Field(
        default=None, description="Date of the earliest paper (YYYY-MM-DD)."
    )


DossierRelationName = Literal[
    "revises", "accompanies", "related_to", "second_reading_of"
]


class DossierRelationDTO(BaseModel):
    """A relation between this dossier and another, and which way it points.

    * ``revises``: a supplementary budget or a slotwet revises the budget of its chapter
      and year; ``rule`` says which (``begrotingswijziging`` or ``slotwet``).
    * ``accompanies``: a budget change is submitted with the ``nota`` its title names
      (``voorjaarsnota``, ``najaarsnota``, ``miljoenennota``).
    * ``related_to``: the Kamer relates a case of the one dossier to a case of the other
      (``Zaak.GerelateerdNaar``), mostly a letter of the government to the motion it
      answers. ``cases`` counts the pairs of cases, ``case_kinds`` names their kinds
      (``Brief regering → Motie``).
    * ``second_reading_of``: a change in the Grondwet in its second reading and the dossier of
      its first reading, whose papers explain it: the memorandum of 35785 only refers to those
      of 35418 and 35419.

    ``outgoing`` means this dossier is the subject: 37035-XXII revises 36800-XXII and
    accompanies 37020. On 36800-XXII the same ``revises`` is ``incoming``.
    """

    model_config = ConfigDict(extra="forbid")

    relation: DossierRelationName
    direction: Literal["outgoing", "incoming"]
    dossier: DossierSummaryDTO
    cases: int | None = None
    case_kinds: list[str] = Field(default_factory=list)
    rule: Literal["begrotingswijziging", "slotwet"] | None = None
    nota: Literal["voorjaarsnota", "najaarsnota", "miljoenennota"] | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> DossierRelationDTO:
        meta = row.get("meta") or {}
        return cls(
            relation=cast(DossierRelationName, str(row["relation"]).lower()),
            direction=row["direction"],
            dossier=DossierSummaryDTO.from_document(row["dossier"]),
            cases=meta.get("cases"),
            case_kinds=list(meta.get("case_kinds") or []),
            rule=meta.get("rule"),
            nota=meta.get("nota"),
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
    relations: list[DossierRelationDTO] = Field(
        default_factory=list,
        description=(
            "The dossiers this one revises, accompanies or is related to, and those that "
            "revise, accompany or relate to it: by relation, then outgoing before incoming, "
            "then in the order of their numbers. All dossiers of its own number are "
            "``GET /api/dossiers?number=``."
        ),
    )

    @classmethod
    def from_document(
        cls,
        doc: dict[str, Any],
        *,
        counts: dict[str, int] | None = None,
        hub: dict[str, Any] | None = None,
        relations: list[dict[str, Any]] | None = None,
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
            relations=[DossierRelationDTO.from_row(r) for r in relations or []],
        )


def _dossier_fields(doc: dict[str, Any]) -> dict[str, Any]:
    props = doc.get("props") or {}
    return {
        "id": doc["_id"],
        "key": doc["_key"],
        "number": props.get("label") or "",
        "suffix": props.get("suffix") or None,
        "same_number_count": int(props.get("same_number_count") or 0),
        "title": props.get("title"),
        "short_title": short_title(props.get("title")),
        "title_source": props.get("title_source"),
        "track": props.get("track_kind") or "overig",
        "current_stage": _stage(props.get("current_stage")),
        "stages": _stages(props.get("stages_present")),
        "stages_complete": props.get("stages_complete") is not False,
        "stages_missing": _stages(props.get("stages_missing")),
        "closed": bool(props.get("closed")),
        "outcome": (
            props.get("outcome")
            if props.get("outcome") in get_args(DossierOutcome)
            else None
        ),
        "opened_on": props.get("opened_on"),
        "closed_on": props.get("closed_on"),
        "ministry": props.get("ministry"),
        "initiative": props.get("initiative"),
        "cabinet": props.get("cabinet"),
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

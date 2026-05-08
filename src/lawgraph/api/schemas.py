"""DTO definitions for the FastAPI layer."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

_DROP_PROPS_KEYS = ("raw_xml",)


def _build_node_payload(
    doc: dict[str, Any], *, drop_props_keys: tuple[str, ...] | None = None
) -> dict[str, Any]:
    props: dict[str, Any] = {}
    raw_props = doc.get("props")
    if isinstance(raw_props, dict):
        props = raw_props
    sanitized = {
        key: value for key, value in props.items() if key not in (drop_props_keys or ())
    }
    return {
        "id": doc["_id"],
        "key": doc["_key"],
        "collection": doc["_id"].split("/", 1)[0] if "/" in doc["_id"] else doc["_id"],
        "type": doc.get("type", ""),
        "display_name": props.get("display_name"),
        "labels": list(doc.get("labels") or []),
        "props": sanitized or None,
    }


class BaseNodeDTO(BaseModel):
    """Common node representation used by multiple responses."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    collection: str
    type: str
    display_name: str | None
    labels: list[str]
    props: dict[str, Any] | None

    @classmethod
    def from_document(
        cls,
        doc: dict[str, Any],
        *,
        drop_props_keys: tuple[str, ...] | None = _DROP_PROPS_KEYS,
    ) -> BaseNodeDTO:
        payload = _build_node_payload(doc, drop_props_keys=drop_props_keys)
        return cls(**payload)


class InstrumentSummaryDTO(BaseModel):
    """Korte representatie van een instrument voor respondenten."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    display_name: str | None
    article_count: int = 0
    judgment_count: int = 0
    inbound_citation_count: int = 0
    outbound_citation_count: int = 0

    @classmethod
    def from_document(
        cls,
        doc: dict[str, Any],
        *,
        stats: Any = None,
    ) -> InstrumentSummaryDTO:
        props = doc.get("props") or {}
        s = stats or {}
        return cls(
            id=doc["_id"],
            key=doc["_key"],
            display_name=props.get("display_name"),
            article_count=int(
                getattr(s, "article_count", 0)
                or (s.get("article_count", 0) if isinstance(s, dict) else 0)
            ),  # noqa: E501
            judgment_count=int(
                getattr(s, "judgment_count", 0)
                or (s.get("judgment_count", 0) if isinstance(s, dict) else 0)
            ),  # noqa: E501
            inbound_citation_count=int(
                getattr(s, "inbound_citation_count", 0)
                or (s.get("inbound_citation_count", 0) if isinstance(s, dict) else 0)
            ),  # noqa: E501
            outbound_citation_count=int(
                getattr(s, "outbound_citation_count", 0)
                or (s.get("outbound_citation_count", 0) if isinstance(s, dict) else 0)
            ),  # noqa: E501
        )


class ArticleSummaryDTO(BaseModel):
    """Samenvatting van een artikel met identificatie en tekst."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    bwb_id: str | None
    article_number: str | None
    display_name: str | None
    text: str | None

    @classmethod
    def from_document(
        cls,
        doc: dict[str, Any],
    ) -> ArticleSummaryDTO:
        props = doc.get("props") or {}
        return cls(
            id=doc["_id"],
            key=doc["_key"],
            bwb_id=props.get("bwb_id"),
            article_number=props.get("article_number"),
            display_name=props.get("display_name"),
            text=props.get("text"),
        )


class ArticleCitationTarget(BaseModel):
    """Minimal metadata describing the referenced article."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    collection: str
    bwb_id: str | None
    article_number: str | None
    display_name: str | None


class ArticleCitationSpan(BaseModel):
    """Character span for an internal citation inside the source article."""

    model_config = ConfigDict(extra="forbid")

    start: int | None
    end: int | None
    text: str | None
    target: ArticleCitationTarget
    kind: str = "article"
    confidence: float | None = None


class JudgmentDTO(BaseNodeDTO):
    """Rich judgment DTO that hides raw XML but exposes metadata."""

    ecli: str | None
    summary: str | None
    paragraphs: list["JudgmentParagraph"] = Field(default_factory=list)

    @classmethod
    def from_document(
        cls,
        doc: dict[str, Any],
        *,
        drop_props_keys: tuple[str, ...] | None = _DROP_PROPS_KEYS,
    ) -> JudgmentDTO:
        base = BaseNodeDTO.from_document(doc, drop_props_keys=drop_props_keys)
        props = doc.get("props") or {}
        raw_paragraphs = props.get("paragraphs") or []
        paragraphs = [
            JudgmentParagraph(
                number=p.get("number"),
                kind=p.get("kind"),
                text=p.get("text") or "",
            )
            for p in raw_paragraphs
            if isinstance(p, dict) and p.get("text")
        ]
        return cls(
            **base.model_dump(),
            ecli=props.get("ecli"),
            summary=props.get("summary") or props.get("strafrecht_profile"),
            paragraphs=paragraphs,
        )


class JudgmentSummaryDTO(BaseModel):
    """Lightweight judgment summary for listing matches."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    display_name: str | None
    ecli: str | None

    @classmethod
    def from_document(cls, doc: dict[str, Any]) -> JudgmentSummaryDTO:
        props = doc.get("props") or {}
        return cls(
            id=doc["_id"],
            key=doc["_key"],
            display_name=props.get("display_name"),
            ecli=props.get("ecli"),
        )


class ArticleRelationDTO(BaseModel):
    """Article reference plus optional parent instrument used in judgment responses."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    display_name: str | None
    bwb_id: str | None
    article_number: str | None
    instrument: InstrumentSummaryDTO | None

    @classmethod
    def from_documents(
        cls,
        article_doc: dict[str, Any],
        instrument_doc: dict[str, Any] | None,
    ) -> ArticleRelationDTO:
        props = article_doc.get("props") or {}
        instrument = (
            InstrumentSummaryDTO.from_document(instrument_doc)
            if instrument_doc
            else None
        )
        return cls(
            id=article_doc["_id"],
            key=article_doc["_key"],
            display_name=props.get("display_name"),
            bwb_id=props.get("bwb_id"),
            article_number=props.get("article_number"),
            instrument=instrument,
        )


class ArticleDetailResponse(BaseModel):
    """Response model voor het artikel endpoint."""

    article: ArticleSummaryDTO
    instrument: InstrumentSummaryDTO | None
    judgments: list[JudgmentSummaryDTO]
    citations: list[ArticleCitationSpan] = Field(default_factory=list)
    metadata: dict[str, Any] | None


class JudgmentParagraph(BaseModel):
    """A single paragraph from a judgment, optionally with inline article citations."""

    model_config = ConfigDict(extra="forbid")

    number: int | None = None
    kind: str | None = None
    text: str
    citaties: list[ArticleCitationSpan] = Field(default_factory=list)


class JudgmentDetailResponse(BaseModel):
    """Response model for judgment detail endpoint."""

    judgment: JudgmentDTO
    articles: list[ArticleRelationDTO]
    cited_judgments: list[JudgmentSummaryDTO] = Field(default_factory=list)
    metadata: dict[str, Any] | None


class NeighborDTO(BaseModel):
    """Neighbor view used by the generic node explorer."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    collection: str
    type: str
    display_name: str | None
    labels: list[str]
    props: dict[str, Any] | None
    relation: str | None
    direction: Literal["outbound", "inbound"]
    confidence: float | None

    @classmethod
    def from_entry(
        cls,
        doc: dict[str, Any],
        relation: str | None,
        direction: Literal["outbound", "inbound"],
        confidence: float | None,
    ) -> NeighborDTO:
        payload = _build_node_payload(doc)
        return cls(
            **payload, relation=relation, direction=direction, confidence=confidence
        )


class NodeNeighborsDTO(BaseModel):
    all: list[NeighborDTO] = Field(default_factory=list)
    # Backwards-compat aliases — kept so old consumers don't break.
    strict: list[NeighborDTO] = Field(default_factory=list)
    semantic: list[NeighborDTO] = Field(default_factory=list)


class NodeGraphResponse(BaseModel):
    node: BaseNodeDTO
    neighbors: NodeNeighborsDTO


# ── Parliamentary dossier schemas ─────────────────────────────────────────────


class PartijStemDTO(BaseModel):
    """One party's contribution to a vote."""

    model_config = ConfigDict(extra="forbid")

    partij: str
    aantal_zetels: int


class StemmingDTO(BaseModel):
    """Aggregated vote result for one motion/wetsvoorstel."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    datum: str | None = None
    onderwerp: str | None = None
    aangenomen: bool
    stemwijze: str = "fractie"
    voor: list[PartijStemDTO] = Field(default_factory=list)
    tegen: list[PartijStemDTO] = Field(default_factory=list)
    onthouding: list[PartijStemDTO] = Field(default_factory=list)

    @classmethod
    def from_document(cls, doc: dict[str, Any]) -> StemmingDTO:
        props = doc.get("props") or {}
        return cls(
            id=doc["_id"],
            key=doc["_key"],
            datum=props.get("datum"),
            onderwerp=props.get("onderwerp"),
            aangenomen=bool(props.get("aangenomen")),
            stemwijze=props.get("stemwijze") or "fractie",
            voor=[
                PartijStemDTO(**v)
                for v in (props.get("voor") or [])
                if isinstance(v, dict)
            ],
            tegen=[
                PartijStemDTO(**v)
                for v in (props.get("tegen") or [])
                if isinstance(v, dict)
            ],
            onthouding=[
                PartijStemDTO(**v)
                for v in (props.get("onthouding") or [])
                if isinstance(v, dict)
            ],
        )


class ToezeggingDTO(BaseModel):
    """Ministerial commitment made during a debate."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    tekst: str | None = None
    minister_naam: str | None = None
    minister_functie: str | None = None
    gedaan_op: str | None = None
    verwachte_afhandeling: str | None = None
    status: str = "open"

    @classmethod
    def from_document(cls, doc: dict[str, Any]) -> ToezeggingDTO:
        props = doc.get("props") or {}
        return cls(
            id=doc["_id"],
            key=doc["_key"],
            tekst=props.get("tekst"),
            minister_naam=props.get("minister_naam"),
            minister_functie=props.get("minister_functie"),
            gedaan_op=props.get("gedaan_op"),
            verwachte_afhandeling=props.get("verwachte_afhandeling"),
            status=props.get("status") or "open",
        )


class ActiviteitDTO(BaseModel):
    """Parliamentary debate or hearing entry."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    datum: str | None = None
    agenda_titel: str | None = None
    soort: str | None = None
    commissie_id: str | None = None
    video_url: str | None = None

    @classmethod
    def from_document(cls, doc: dict[str, Any]) -> ActiviteitDTO:
        props = doc.get("props") or {}
        return cls(
            id=doc["_id"],
            key=doc["_key"],
            datum=props.get("datum"),
            agenda_titel=props.get("agenda_titel"),
            soort=props.get("soort"),
            commissie_id=props.get("commissie_id"),
            video_url=props.get("video_url"),
        )


class PublicationSummaryDTO(BaseModel):
    """Lightweight TK publication for timeline listing."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    datum: str | None = None
    soort: str | None = None
    titel: str | None = None
    external_id: str | None = None

    @classmethod
    def from_document(cls, doc: dict[str, Any]) -> PublicationSummaryDTO:
        props = doc.get("props") or {}
        raw = props.get("raw") or {}
        datum = props.get("datum") or raw.get("Datum")
        if datum and "T" in str(datum):
            datum = str(datum).split("T")[0]
        return cls(
            id=doc["_id"],
            key=doc["_key"],
            datum=datum,
            soort=props.get("soort"),
            titel=props.get("title") or props.get("display_name"),
            external_id=props.get("external_id"),
        )


class TimelineEntryDTO(BaseModel):
    """One entry in a dossier timeline.

    The `body` field is a discriminated union: its contents depend on `soort`.
    """

    model_config = ConfigDict(extra="forbid")

    datum: str | None
    soort: str
    titel: str | None
    node_id: str
    node_type: str
    body: dict[str, Any] = Field(default_factory=dict)


class DossierSummaryDTO(BaseModel):
    """Short representation of a Kamerstukdossier for list views."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    kamerstuknummer: str
    titel: str | None = None
    huidige_fase: str | None = None
    afgedaan: bool = False
    geopend_op: str | None = None
    gesloten_op: str | None = None

    @classmethod
    def from_document(cls, doc: dict[str, Any]) -> DossierSummaryDTO:
        props = doc.get("props") or {}
        return cls(
            id=doc["_id"],
            key=doc["_key"],
            kamerstuknummer=props.get("kamerstuknummer")
            or str(props.get("nummer") or ""),
            titel=props.get("titel"),
            huidige_fase=props.get("huidige_fase"),
            afgedaan=bool(props.get("afgedaan")),
            geopend_op=props.get("geopend_op"),
            gesloten_op=props.get("gesloten_op"),
        )


class DossierDetailResponse(BaseModel):
    """Full dossier detail response."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    kamerstuknummer: str
    titel: str | None = None
    huidige_fase: str | None = None
    afgedaan: bool = False
    geopend_op: str | None = None
    gesloten_op: str | None = None
    document_count: int = 0
    activiteit_count: int = 0
    stemming_count: int = 0
    toezegging_count: int = 0

    @classmethod
    def from_document(
        cls,
        doc: dict[str, Any],
        *,
        document_count: int = 0,
        activiteit_count: int = 0,
        stemming_count: int = 0,
        toezegging_count: int = 0,
    ) -> DossierDetailResponse:
        props = doc.get("props") or {}
        return cls(
            id=doc["_id"],
            key=doc["_key"],
            kamerstuknummer=props.get("kamerstuknummer")
            or str(props.get("nummer") or ""),
            titel=props.get("titel"),
            huidige_fase=props.get("huidige_fase"),
            afgedaan=bool(props.get("afgedaan")),
            geopend_op=props.get("geopend_op"),
            gesloten_op=props.get("gesloten_op"),
            document_count=document_count,
            activiteit_count=activiteit_count,
            stemming_count=stemming_count,
            toezegging_count=toezegging_count,
        )


class DossierTimelineResponse(BaseModel):
    """Dossier timeline — ordered list of documents, activiteiten, stemmingen, toezeggingen."""

    model_config = ConfigDict(extra="forbid")

    kamerstuknummer: str
    total: int
    order: str
    entries: list[TimelineEntryDTO]


class DossierMutationNode(BaseModel):
    """A node in the pending-mutation subgraph."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    collection: str
    type: str
    display_name: str | None
    labels: list[str]

    @classmethod
    def from_document(cls, doc: dict[str, Any]) -> DossierMutationNode:
        props = doc.get("props") or {}
        raw_id = doc.get("_id", "")
        return cls(
            id=raw_id,
            key=doc.get("_key", ""),
            collection=raw_id.split("/")[0] if "/" in raw_id else "",
            type=doc.get("type", ""),
            display_name=props.get("display_name"),
            labels=list(doc.get("labels") or []),
        )


class DossierMutationEdge(BaseModel):
    """An edge in the pending-mutation subgraph."""

    model_config = ConfigDict(extra="forbid")

    from_id: str | None
    to_id: str | None
    relation: str | None
    status: str | None
    meta: dict[str, Any] | None = None


class DossierMutationsResponse(BaseModel):
    """Pending-mutation subgraph for a dossier.

    Shape is compatible with the existing graph endpoint so the frontend can
    render it directly.
    """

    model_config = ConfigDict(extra="forbid")

    kamerstuknummer: str
    nodes: list[DossierMutationNode]
    edges: list[DossierMutationEdge]


class LegislativeHistoryEntry(BaseModel):
    """One entry in the legislative history of an article."""

    model_config = ConfigDict(extra="forbid")

    dossier_id: str | None = None
    dossier_nummer: str | None = None
    dossier_titel: str | None = None
    datum: str | None = None
    soort: str | None = None
    status: str | None = None
    samenvatting: str | None = None
    document_id: str | None = None


class ArticleLegislativeHistoryResponse(BaseModel):
    """Legislative history for an article."""

    model_config = ConfigDict(extra="forbid")

    article_id: str
    entries: list[LegislativeHistoryEntry]
    total: int


class ArticleInFluxResponse(BaseModel):
    """In-flux status for an article."""

    model_config = ConfigDict(extra="forbid")

    article_id: str
    in_flux: bool
    open_dossier_count: int


class CommissieDTO(BaseModel):
    """Parliamentary committee."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    naam: str | None = None
    afkorting: str | None = None
    slug: str | None = None
    active_dossier_count: int = 0

    @classmethod
    def from_document(
        cls, doc: dict[str, Any], *, active_dossier_count: int = 0
    ) -> CommissieDTO:
        props = doc.get("props") or {}
        return cls(
            id=doc["_id"],
            key=doc["_key"],
            naam=props.get("naam"),
            afkorting=props.get("afkorting"),
            slug=props.get("slug"),
            active_dossier_count=active_dossier_count,
        )


class LidDTO(BaseModel):
    """Parliamentary member or minister."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    naam: str | None = None
    partij: str | None = None
    actief: bool = True

    @classmethod
    def from_document(cls, doc: dict[str, Any]) -> LidDTO:
        props = doc.get("props") or {}
        return cls(
            id=doc["_id"],
            key=doc["_key"],
            naam=props.get("naam"),
            partij=props.get("partij"),
            actief=bool(props.get("actief", True)),
        )


class CommissieDetailDTO(CommissieDTO):
    """Committee detail with leden and recent dossiers."""

    leden: list[LidDTO] = []
    dossiers: list[DossierSummaryDTO] = []

    @classmethod
    def from_detail_document(cls, doc: dict[str, Any]) -> CommissieDetailDTO:
        props = doc.get("props") or {}
        leden = [LidDTO.from_document(lid) for lid in doc.get("leden") or []]
        dossiers = [
            DossierSummaryDTO.from_document(d) for d in doc.get("dossiers") or []
        ]
        return cls(
            id=doc["_id"],
            key=doc["_key"],
            naam=props.get("naam"),
            afkorting=props.get("afkorting"),
            slug=props.get("slug"),
            active_dossier_count=len([d for d in dossiers if not d.afgedaan]),
            leden=leden,
            dossiers=dossiers,
        )


# ── Party colors ─────────────────────────────────────────────────────────────
# Canonical brand colors for Dutch parliamentary parties.
# Used by the frontend to color stemming chips.

PARTY_COLORS: dict[str, str] = {
    "VVD": "#003082",
    "D66": "#1DB954",
    "PVV": "#002868",
    "CDA": "#399E48",
    "SP": "#EE1C25",
    "PvdA": "#E63325",
    "GroenLinks": "#46962B",
    "GL-PvdA": "#46962B",
    "ChristenUnie": "#4F95D4",
    "Volt": "#592D82",
    "NSC": "#1B4F72",
    "BBB": "#9ECA3C",
    "JA21": "#CC0000",
    "SGP": "#FF6600",
    "FvD": "#8B0000",
    "DENK": "#39B54A",
    "BIJ1": "#FFCC00",
    "50PLUS": "#8B008B",
    "PvdD": "#4CAF50",
    "Groep Van Haga": "#002868",
}


class PartyColorsResponse(BaseModel):
    """Party abbreviation → hex color map for the frontend."""

    model_config = ConfigDict(extra="forbid")

    colors: dict[str, str]


# ── Search schemas ────────────────────────────────────────────────────────────

SEARCH_TYPES = frozenset(
    {"articles", "judgments", "dossiers", "publications", "commissies"}
)


class SearchResultItem(BaseModel):
    """One search hit, typed by collection."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    collection: str
    type: str
    display_name: str | None
    snippet: str | None = None
    score: float = 1.0
    extra: dict[str, Any] = Field(default_factory=dict)


class SearchResponse(BaseModel):
    """Full-text search response, grouped by type."""

    model_config = ConfigDict(extra="forbid")

    q: str
    types: list[str]
    total: int
    results: dict[str, list[SearchResultItem]]


class EdgeStatsDTO(BaseModel):
    """Edge counts: total and per relation type."""

    model_config = ConfigDict(extra="forbid")

    total: int
    by_relation: dict[str, int]


class InstrumentLayerInstrumentDTO(BaseModel):
    """Instrument node in the instrument-layer graph."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    bwb_id: str | None = None
    display_name: str | None = None
    citation_title: str | None = None
    title: str | None = None
    shorthand: str | None = None
    jurisdiction: str | None = None
    stub: bool = False
    citation_count: int = 0

    @classmethod
    def from_document(
        cls,
        doc: dict[str, Any],
        *,
        stats: dict[str, Any] | None = None,
    ) -> InstrumentLayerInstrumentDTO:
        props = doc.get("props") or {}
        return cls(
            id=doc["_id"],
            key=doc["_key"],
            bwb_id=props.get("bwb_id"),
            display_name=(
                props.get("display_name")
                or props.get("citation_title")
                or props.get("title")
            ),
            citation_title=props.get("citation_title"),
            title=props.get("title"),
            shorthand=props.get("short_title") or props.get("shorthand"),
            jurisdiction=props.get("jurisdiction"),
            stub=bool(props.get("stub", False)),
            citation_count=int((stats or {}).get("citation_count", 0)),
        )


class JudgmentGraphNodeDTO(BaseModel):
    """Judgment node in the judgment-layer or global graph."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    display_name: str | None = None
    shorthand: str | None = None
    ecli: str | None = None
    stub: bool = False

    @classmethod
    def from_document(cls, doc: dict[str, Any]) -> JudgmentGraphNodeDTO:
        props = doc.get("props") or {}
        return cls(
            id=doc["_id"],
            key=doc["_key"],
            display_name=props.get("display_name") or props.get("ecli"),
            shorthand=props.get("shorthand"),
            ecli=props.get("ecli"),
            stub=bool(props.get("stub", False)),
        )


class ArticleGraphNodeDTO(BaseModel):
    """Article node for the global graph."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    bwb_id: str | None = None
    article_number: str | None = None
    display_name: str | None = None

    @classmethod
    def from_document(cls, doc: dict[str, Any]) -> ArticleGraphNodeDTO:
        props = doc.get("props") or {}
        return cls(
            id=doc["_id"],
            key=doc["_key"],
            bwb_id=props.get("bwb_id"),
            article_number=props.get("article_number"),
            display_name=props.get("display_name"),
        )


class GraphEdgeDTO(BaseModel):
    """Graph edge with optional text annotation (for global/article-level graphs)."""

    model_config = ConfigDict(extra="forbid")

    from_id: str
    to_id: str
    relation_type: str
    start: int | None = None
    end: int | None = None
    text: str | None = None
    confidence: float | None = None


class InstrumentEdgeDTO(BaseModel):
    """Aggregated instrument-layer edge with weight."""

    model_config = ConfigDict(extra="forbid")

    from_id: str
    to_id: str
    relation_type: str
    weight: float | None = None
    confidence: float | None = None


class InstrumentLayerGraphResponse(BaseModel):
    """Response for GET /api/graph/instruments."""

    model_config = ConfigDict(extra="forbid")

    instruments: list[InstrumentLayerInstrumentDTO]
    edges: list[InstrumentEdgeDTO]
    metadata: dict[str, Any] | None = None


class JudgmentLayerGraphResponse(BaseModel):
    """Response for GET /api/graph/judgments."""

    model_config = ConfigDict(extra="forbid")

    judgments: list[JudgmentGraphNodeDTO]
    instruments: list[InstrumentLayerInstrumentDTO]
    edges: list[InstrumentEdgeDTO]
    metadata: dict[str, Any] | None = None


class PublicationSummary(BaseModel):
    """Lightweight TK publication row for the publications index page."""

    model_config = ConfigDict(extra="forbid")

    key: str
    title: str | None = None
    soort: str | None = None
    datum: str | None = None
    external_id: str | None = None
    has_text: bool = False
    linked_articles: int = 0


class PublicationListResponse(BaseModel):
    """Paginated list of TK publication summaries."""

    model_config = ConfigDict(extra="forbid")

    total: int
    items: list[PublicationSummary]


class PublicationTextResponse(BaseModel):
    """Full TK publication with text content."""

    model_config = ConfigDict(extra="forbid")

    key: str
    publication_id: str
    title: str | None = None
    soort: str | None = None
    datum: str | None = None
    external_id: str | None = None
    tk_url: str | None = None
    text: str | None = None


class StatsResponse(BaseModel):
    """Database statistics: document counts per collection and edge counts."""

    model_config = ConfigDict(extra="forbid")

    nodes: dict[str, int]
    edges: EdgeStatsDTO

"""DTO definitions for the FastAPI layer.

Conventions across the API
--------------------------
* Every DTO has ``model_config = ConfigDict(extra="forbid")``. Unknown
  fields in inputs/outputs raise validation errors so contract drift
  surfaces immediately instead of being silently tolerated.
* Node-id references always use ``id`` (the Arango ``_id``,
  ``collection/key``) and ``key`` (the Arango ``_key``). Never
  ``article_id``/``dossier_id`` etc. — readers can split ``id`` if they
  need the collection prefix.
* Edges use ``from``/``to`` (matching the Arango edge shape and the
  graph-rendering convention).
* List responses expose two fields: ``items`` (the page, after ``limit``
  /``offset``) and ``total`` (the **absolute** count of matches,
  independent of ``limit`` — for "+N more" badges and pagination).
* Bulk endpoints return ``response_class=JSONResponse`` only when the
  payload is a free-form map (``dict[str, int]``: heat counts, in-flux
  counts). Every other response is a typed Pydantic model.
"""

from __future__ import annotations

from typing import Any, Literal, get_args

from pydantic import BaseModel, ConfigDict, Field

from lawgraph.config.constants import PARTY_COLORS as PARTY_COLORS

_DROP_PROPS_KEYS = ("raw_xml",)

# Props that bloat the wire size of graph-view payloads without serving any
# frontend rendering need. Stripped from focal node + every neighbor on the
# /api/nodes/{coll}/{key} response. The detail endpoints
# (/api/judgments/{ecli}, /api/articles/...) still return them when the
# reader actually needs the body.
DROP_PROPS_KEYS_GRAPH = (
    "raw_xml",
    "text",
    "paragraphs",
    "leden",
    "subjects",
    "judgment_metadata",
    "raw_data",
    "raw",  # publications carry the source TK payload here
)


def _derive_source_from_ecli(ecli: str | None) -> str | None:
    """Derive judgment source from ECLI prefix when props.source is not stored."""
    if not ecli:
        return None
    if ecli.startswith("ECLI:NL:"):
        return "rechtspraak"
    if ecli.startswith("ECLI:CE:ECHR:"):
        return "echr"
    if ecli.startswith("ECLI:EU:"):
        return "cjeu"
    return None


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
        """Build from an ArangoDB document and an optional InstrumentStats dataclass."""
        props = doc.get("props") or {}
        return cls(
            id=doc["_id"],
            key=doc["_key"],
            display_name=props.get("display_name"),
            article_count=int(getattr(stats, "article_count", 0) or 0),
            judgment_count=int(getattr(stats, "judgment_count", 0) or 0),
            inbound_citation_count=int(getattr(stats, "inbound_citation_count", 0) or 0),
            outbound_citation_count=int(getattr(stats, "outbound_citation_count", 0) or 0),
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


class InstrumentArticleBreadcrumbDTO(BaseModel):
    """One step in an article's chapter/section path."""

    model_config = ConfigDict(extra="forbid")

    type: str | None = None
    label: str | None = None


class InstrumentArticleNodeDTO(BaseModel):
    """Lightweight article shape for the graph-loader.

    No full ``text`` field — that would balloon the payload when loading
    hundreds of articles for a single instrument. ``text_preview`` carries
    the first few characters so the FE has something to render on the node;
    use /api/articles/{bwb_id}/{article_number} for full content.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    bwb_id: str | None
    article_number: str | None
    display_name: str | None
    breadcrumb: list[InstrumentArticleBreadcrumbDTO] = []
    stub: bool = False
    text_preview: str | None = None

    @classmethod
    def from_document(
        cls, doc: dict[str, Any], *, text_preview_chars: int = 160
    ) -> InstrumentArticleNodeDTO:
        props = doc.get("props") or {}
        text = props.get("text") or ""
        raw_crumbs = props.get("breadcrumb") or []
        crumbs = [
            InstrumentArticleBreadcrumbDTO(type=c.get("type"), label=c.get("label"))
            for c in raw_crumbs
            if isinstance(c, dict)
        ]
        return cls(
            id=doc["_id"],
            key=doc["_key"],
            bwb_id=props.get("bwb_id"),
            article_number=props.get("article_number"),
            display_name=props.get("display_name"),
            breadcrumb=crumbs,
            stub=bool(props.get("stub", False)),
            text_preview=(text[:text_preview_chars] if text else None),
        )


class InstrumentArticlesResponse(BaseModel):
    """Response for GET /api/instruments/{bwb_id}/articles."""

    model_config = ConfigDict(extra="forbid")

    bwb_id: str
    total: int = Field(
        ...,
        description=(
            "Absolute count of articles matching the request, independent "
            "of ``limit`` — use to render a '+N more' badge."
        ),
    )
    items: list[InstrumentArticleNodeDTO]


# ── /api/instruments/{bwb_id}/citations (bulk edges) ──────────────────────


class InstrumentCitationEdge(BaseModel):
    """One edge incident to an article of the focal instrument.

    Edges keep ``from``/``to`` (not ``source``/``target``) — that matches
    the ArangoDB edge shape and the citation graph rendering convention.
    For an article-node id reference inside other DTOs, ``id``/``key`` are
    used instead.
    """

    model_config = ConfigDict(extra="forbid")

    from_id: str = Field(..., alias="from", description="Edge source node _id")
    to_id: str = Field(..., alias="to", description="Edge target node _id")
    relation: str = Field(..., description="Edge relation type, e.g. CITES_ARTICLE")
    direction: Literal["in", "out", "intra"] = Field(
        ...,
        description=(
            "Relative to the focal instrument: ``out`` = source is in this "
            "wet, ``in`` = target is in this wet, ``intra`` = both sides."
        ),
    )
    meta: dict[str, Any] | None = Field(
        None, description="Optional edge metadata as written by the pipeline."
    )


class InstrumentCitationsResponse(BaseModel):
    """Response for GET /api/instruments/{bwb_id}/citations.

    One-shot bundle of every edge incident to the instrument's articles plus
    the foreign endpoints those edges point at, grouped by collection.
    """

    model_config = ConfigDict(extra="forbid")

    bwb_id: str
    article_count: int = Field(
        ..., description="Number of articles in the focal instrument."
    )
    total_edges: int = Field(
        ..., description="Number of edges in the response (capped by ``max_edges``)."
    )
    edges: list[InstrumentCitationEdge]
    nodes: dict[str, list[dict[str, Any]]] = Field(
        ...,
        description=(
            "Foreign endpoints grouped by collection name "
            "(e.g. ``{'judgments': [...], 'instrument_articles': [...]}``)."
        ),
    )


# ── /api/instruments/{bwb_id}/judgments ───────────────────────────────────


class CitedArticleRef(BaseModel):
    """Reference to one cited article inside a judgment-citation list."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(
        ...,
        description="ArangoDB document _id, e.g. ``instrument_articles/bwbr0001854_287``.",
    )
    key: str = Field(..., description="ArangoDB document _key.")
    article_number: str | None = None
    display_name: str | None = None


class InstrumentJudgmentItem(BaseModel):
    """One judgment that cites this instrument."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(
        ...,
        description="ArangoDB document _id, e.g. ``judgments/ecli_nl_hr_2014_1496``.",
    )
    key: str
    ecli: str | None = None
    display_name: str | None = None
    cited_articles: list[CitedArticleRef] = Field(
        default_factory=list,
        description="Articles of the focal instrument that this judgment cites.",
    )


class InstrumentJudgmentsResponse(BaseModel):
    """Response for GET /api/instruments/{bwb_id}/judgments."""

    model_config = ConfigDict(extra="forbid")

    bwb_id: str
    total: int = Field(
        ...,
        description=(
            "Absolute number of judgments citing this instrument "
            "(independent of ``limit``)."
        ),
    )
    items: list[InstrumentJudgmentItem]


# ── /api/instruments/{bwb_id}/dossiers ────────────────────────────────────


class InstrumentDossierItem(BaseModel):
    """One Kamerstukdossier touching this instrument."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    kamerstuknummer: str | None = None
    titel: str | None = None
    display_name: str | None = None
    huidige_fase: str | None = None
    geopend_op: str | None = None
    afgedaan: bool | None = None


class InstrumentDossiersResponse(BaseModel):
    """Response for GET /api/instruments/{bwb_id}/dossiers."""

    model_config = ConfigDict(extra="forbid")

    bwb_id: str
    total: int = Field(
        ...,
        description=(
            "Absolute number of dossiers touching this instrument "
            "(independent of ``limit``)."
        ),
    )
    items: list[InstrumentDossierItem]


# ── /api/instruments/{bwb_id}/related-instruments ─────────────────────────


class InstrumentRelatedItem(BaseModel):
    """One other instrument linked via cross-article REFERS_TO_ARTICLE."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    bwb_id: str | None = None
    display_name: str | None = None
    citation_title: str | None = None
    outbound_count: int = Field(
        ...,
        description=(
            "Number of REFERS_TO_ARTICLE edges from articles of the focal "
            "instrument to articles of this related instrument."
        ),
    )
    inbound_count: int = Field(
        ...,
        description="Mirror of ``outbound_count`` in the opposite direction.",
    )


class InstrumentRelatedResponse(BaseModel):
    """Response for GET /api/instruments/{bwb_id}/related-instruments."""

    model_config = ConfigDict(extra="forbid")

    bwb_id: str
    total: int = Field(
        ...,
        description=(
            "Absolute number of related instruments " "(independent of ``limit``)."
        ),
    )
    items: list[InstrumentRelatedItem]


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

    model_config = ConfigDict(extra="forbid")

    ecli: str | None
    source: str | None = None
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
        ecli = props.get("ecli")
        source = props.get("source") or _derive_source_from_ecli(ecli)
        return cls(
            **base.model_dump(),
            ecli=ecli,
            source=source,
            summary=props.get("summary"),
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
    """Response for GET /api/articles/{bwb_id}/{article_number}."""

    model_config = ConfigDict(extra="forbid")

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
    citations: list[ArticleCitationSpan] = Field(default_factory=list)


class JudgmentDetailResponse(BaseModel):
    """Response for GET /api/judgments/{ecli}."""

    model_config = ConfigDict(extra="forbid")

    judgment: JudgmentDTO
    articles: list[ArticleRelationDTO]
    cited_judgments: list[JudgmentSummaryDTO] = Field(default_factory=list)
    metadata: dict[str, Any] | None


class InstrumentListItemDTO(BaseModel):
    """Row in the paginated /api/instruments list."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    collection: str = "instruments"
    bwb_id: str | None
    celex: str | None
    title: str | None
    short_title: str | None
    citation_title: str | None
    jurisdiction: str | None
    kind: str | None
    article_count: int
    judgment_citation_count: int | None = None
    last_article_mutation: str | None = None

    @classmethod
    def from_document(cls, row: dict[str, Any]) -> InstrumentListItemDTO:
        return cls(
            id=row["_id"],
            key=row["_key"],
            bwb_id=row.get("bwb_id"),
            celex=row.get("celex"),
            title=row.get("title"),
            short_title=row.get("short_title"),
            citation_title=row.get("citation_title"),
            jurisdiction=row.get("jurisdiction") or None,
            kind=row.get("kind"),
            article_count=int(row.get("article_count") or 0),
        )


class InstrumentListResponse(BaseModel):
    """Paginated list envelope for instruments."""

    model_config = ConfigDict(extra="forbid")

    items: list[InstrumentListItemDTO]
    total: int


class InstrumentVersionDTO(BaseModel):
    """One historical version (toestand) of a BWB instrument."""

    model_config = ConfigDict(extra="forbid")

    key: str
    bwb_id: str
    valid_from: str | None = None
    valid_until: str | None = None
    current: bool = False
    toestand_url: str | None = None
    article_count: int | None = None

    @classmethod
    def from_document(cls, doc: dict[str, Any]) -> "InstrumentVersionDTO":
        props = doc.get("props") or {}
        return cls(
            key=doc["_key"],
            bwb_id=props.get("bwb_id", ""),
            valid_from=props.get("valid_from"),
            valid_until=props.get("valid_until"),
            current=bool(props.get("current", False)),
            toestand_url=props.get("toestand_url"),
            article_count=props.get("article_count"),
        )


class InstrumentVersionsResponse(BaseModel):
    """Paginated list of historical versions for one instrument."""

    model_config = ConfigDict(extra="forbid")

    bwb_id: str
    total: int
    items: list[InstrumentVersionDTO]


class InstrumentArticleVersionDTO(BaseModel):
    """One historical version of a single BWB article."""

    model_config = ConfigDict(extra="forbid")

    key: str
    bwb_id: str
    article_number: str
    valid_from: str | None = None
    valid_until: str | None = None
    current: bool = False
    text: str | None = None
    diff: str | None = None  # unified diff vs previous version (computed on-the-fly)


class InstrumentArticleVersionsResponse(BaseModel):
    """All historical versions of one article, newest first."""

    model_config = ConfigDict(extra="forbid")

    bwb_id: str
    article_number: str
    items: list[InstrumentArticleVersionDTO]


class InstrumentArticlesAtResponse(BaseModel):
    """Articles of an instrument as-of a specific date."""

    model_config = ConfigDict(extra="forbid")

    bwb_id: str
    at_date: str
    total: int
    items: list[InstrumentArticleVersionDTO]


class JudgmentListItemDTO(BaseModel):
    """Row in the paginated /api/judgments list."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    collection: str = "judgments"
    ecli: str | None
    display_name: str | None
    court: str | None
    tier: str | None
    date: str | None
    summary: str | None
    source: str | None = None
    inbound_citation_count: int | None
    outbound_citation_count: int | None = None

    @classmethod
    def from_document(cls, row: dict[str, Any]) -> JudgmentListItemDTO:
        inbound = row.get("inbound_citation_count")
        ecli = row.get("ecli")
        source = row.get("source") or _derive_source_from_ecli(ecli)
        return cls(
            id=row["_id"],
            key=row["_key"],
            ecli=ecli,
            display_name=row.get("display_name") or ecli,
            court=row.get("court_code"),
            tier=row.get("tier"),
            date=row.get("date"),
            summary=row.get("summary"),
            source=source,
            inbound_citation_count=int(inbound) if inbound is not None else None,
        )


class JudgmentListResponse(BaseModel):
    """Paginated list envelope for judgments."""

    model_config = ConfigDict(extra="forbid")

    items: list[JudgmentListItemDTO]
    total: int


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
        payload = _build_node_payload(doc, drop_props_keys=DROP_PROPS_KEYS_GRAPH)
        return cls(
            **payload, relation=relation, direction=direction, confidence=confidence
        )


class NodeNeighborsDTO(BaseModel):
    """Neighbor sets returned by /api/nodes/{collection}/{key}.

    ``all`` is authoritative. ``strict``/``semantic`` are deprecated
    back-compat aliases that mirror ``all``; new consumers should ignore them.
    """

    model_config = ConfigDict(extra="forbid")

    all: list[NeighborDTO] = Field(default_factory=list)
    strict: list[NeighborDTO] = Field(default_factory=list, deprecated=True)
    semantic: list[NeighborDTO] = Field(default_factory=list, deprecated=True)


class NodeGraphResponse(BaseModel):
    """Response for GET /api/nodes/{collection}/{key}."""

    model_config = ConfigDict(extra="forbid")

    node: BaseNodeDTO
    neighbors: NodeNeighborsDTO


class NodeNeighborhoodEdge(BaseModel):
    """Edge in a BFS-neighborhood response."""

    model_config = ConfigDict(extra="forbid")

    id: str
    source: str
    target: str
    relation: str | None
    confidence: float | None = None
    status: str | None = None


class NodeNeighborhoodResponse(BaseModel):
    """One-shot N-hop neighborhood: focal + reachable nodes + spanning edges."""

    model_config = ConfigDict(extra="forbid")

    focal_id: str
    nodes: list[BaseNodeDTO]
    edges: list[NodeNeighborhoodEdge]


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
    besluit_id: str | None = None
    aangenomen: bool
    chamber: str | None = None
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
            besluit_id=props.get("besluit_id"),
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
    tk_url: str | None = None
    body: dict[str, Any] = Field(default_factory=dict)


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


def _coerce_dossier_stage(value: Any) -> DossierStage | None:
    """Map legacy / unknown huidige_fase sentinels onto None.

    'overig' and 'onbekend' were earlier sentinels meaning 'no recognised
    stage'; the read path treats them as missing. Anything outside the
    DossierStage Literal collapses to None so the DTO validates and callers
    see a single null sentinel rather than two.
    """
    _valid = get_args(DossierStage)
    if value in _valid:
        return value
    return None


def _coerce_stages_list(values: Any) -> list[DossierStage]:
    _valid = get_args(DossierStage)
    return [v for v in (values or []) if v in _valid]


TitelSource = Literal["dossier", "document", "activiteit"]
TrajectKind = Literal[
    "wetsvoorstel",
    "initiatiefwetsvoorstel",
    "begroting",
    "motie",
    "overig",
]


class LidVoteEntryDTO(BaseModel):
    """One historical vote cast by a parliamentary member.

    The member's party at the time of the vote is preserved on
    ``partij_at_time`` (their party may have changed after the vote).
    """

    model_config = ConfigDict(extra="forbid")

    stemming_id: str = Field(..., description="Arango _id of the stemming.")
    stemming_key: str
    besluit_id: str | None = None
    datum: str | None = Field(None, description="Date of the vote (YYYY-MM-DD).")
    onderwerp: str | None = None
    aangenomen: bool | None = None
    soort: Literal["Voor", "Tegen", "Onthouden"] = Field(
        ..., description="How the member's party voted."
    )
    aantal_zetels: int | None = Field(
        None, description="Seats the member's party brought to the vote."
    )
    partij_at_time: str | None = Field(
        None,
        description=(
            "Short label of the member's party as of ``datum``. May differ "
            "from the member's current party."
        ),
    )
    fractie_key: str | None = None


class LidVotesResponse(BaseModel):
    """Response for GET /api/leden/{key}/votes."""

    model_config = ConfigDict(extra="forbid")

    lid_id: str | None = Field(
        None, description="Arango _id of the lid; null when the lid is unknown."
    )
    total: int = Field(
        ...,
        description=(
            "Number of votes returned. The underlying query is capped by "
            "``limit``; this matches that count, not the absolute history."
        ),
    )
    votes: list[LidVoteEntryDTO]


class TouchedInstrumentDTO(BaseModel):
    """One law that an actor (lid or fractie) has touched.

    Returned by ``/api/leden/{key}/touched-instruments`` and
    ``/api/fracties/{key}/touched-instruments``. ``count`` is the number
    of distinct publications by the actor that wijzigen / introduceren /
    trekken in articles of this instrument.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="Arango _id of the instrument.")
    key: str
    display_name: str | None = None
    title: str | None = None
    short_title: str | None = None
    citation_title: str | None = None
    bwb_id: str | None = None
    celex: str | None = None
    count: int = Field(
        ..., description="Distinct publications by the actor that touch this wet."
    )


class TouchedInstrumentsResponse(BaseModel):
    """Wrapper for actor → touched-instruments lists."""

    model_config = ConfigDict(extra="forbid")

    actor_id: str = Field(
        ...,
        description=(
            "Arango _id of the actor (``leden/...`` or ``fracties/...``). "
            "Unified field name so the same response model serves both "
            "endpoints."
        ),
    )
    total: int = Field(
        ...,
        description=("Number of instruments returned (capped by ``limit``)."),
    )
    items: list[TouchedInstrumentDTO]


class FractieDetailDTO(BaseModel):
    """Response for GET /api/fracties/{key}."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    type: str = Field(..., description="Node type label (e.g. ``fractie``).")
    labels: list[str]
    props: dict[str, Any] | None = Field(
        None, description="Raw fractie props as stored on the node."
    )


class StemmingSummaryItemDTO(BaseModel):
    """One row in the /api/stemmingen browser list.

    ``voor_fracties`` / ``tegen_fracties`` / ``onthouding_fracties`` count the
    number of *fracties* (parties) in each camp — typically 10–17.
    ``voor_zetels`` / ``tegen_zetels`` / ``onthouding_zetels`` sum the
    *seats* each camp brings, which is the number to display for a vote result.
    ``besluit_id`` uniquely identifies the motion within a debate; use it to
    link to the motie-tekst rather than ``onderwerp`` which is debate-level.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    datum: str | None = None
    onderwerp: str | None = None
    besluit_id: str | None = None
    dossier_nummers: list[str] = Field(default_factory=list)
    aangenomen: bool | None = None
    voor_fracties: int = 0
    voor_zetels: int = 0
    tegen_fracties: int = 0
    tegen_zetels: int = 0
    onthouding_fracties: int = 0
    onthouding_zetels: int = 0
    chamber: str | None = None


class StemmingListResponse(BaseModel):
    """Response for GET /api/stemmingen."""

    model_config = ConfigDict(extra="forbid")

    total: int = Field(
        ...,
        description=(
            "Absolute number of stemmingen matching the filters "
            "(independent of ``limit``)."
        ),
    )
    items: list[StemmingSummaryItemDTO]


class DossierDocumentDTO(BaseModel):
    """One TK publication linked to a dossier."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    soort: str | None = None
    titel: str | None = None
    volgnummer: int | None = None
    dossier_nummer: str | None = None
    vergaderjaar: str | None = None
    datum: str | None = None
    tk_url: str | None = None
    display_name: str | None = None


class DossierDocumentsResponse(BaseModel):
    """Response for GET /api/dossiers/{kamerstuknummer}/documents."""

    model_config = ConfigDict(extra="forbid")

    total: int = Field(
        ...,
        description=(
            "Absolute number of documents in the dossier " "(independent of ``limit``)."
        ),
    )
    items: list[DossierDocumentDTO]


class DossierDocumentsBulkResponse(BaseModel):
    """Response for GET /api/dossiers/documents/bulk.

    Wrapper around a ``{kamerstuknummer: [docs...]}`` map so the response
    can carry a typed schema and the response_model validates each entry.
    """

    model_config = ConfigDict(extra="forbid")

    items: dict[str, list[DossierDocumentDTO]] = Field(
        ...,
        description=(
            "Map keyed by kamerstuknummer. Each value is the per-dossier "
            "list of documents (capped at ``per_dossier_limit``), most "
            "recent first."
        ),
    )


class DossierSummaryDTO(BaseModel):
    """Short representation of a Kamerstukdossier for list views.

    `traject_kind` is the canonical *kind* of dossier — wetsvoorstel /
    initiatiefwetsvoorstel / begroting / motie / overig — derived from the
    Zaak.Soort chain. It does *not* change as the dossier progresses; use
    this for "is this a wetsvoorstel?" bucketing.

    `huidige_fase` is the *latest recognised* legislative stage seen on the
    dossier's documents/activiteiten (or `'afgehandeld'` for closed dossiers,
    `null` for dossiers with no classifiable signals). `stages_present` lists
    every stage with at least one matching signal, in chronological order —
    use this for any "which stages are present?" UI rather than `huidige_fase`.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    kamerstuknummer: str
    titel: str | None = None
    titel_source: TitelSource | None = None
    traject_kind: TrajectKind | None = None
    huidige_fase: DossierStage | None = None
    stages_present: list[DossierStage] = Field(default_factory=list)
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
            titel_source=props.get("titel_source"),
            traject_kind=props.get("traject_kind") or "overig",
            huidige_fase=_coerce_dossier_stage(props.get("huidige_fase")),
            stages_present=_coerce_stages_list(props.get("stages_present")),
            afgedaan=bool(props.get("afgedaan")),
            geopend_op=props.get("geopend_op"),
            gesloten_op=props.get("gesloten_op"),
        )


class DossierListResponse(BaseModel):
    """Paginated list response for GET /api/dossiers/open and similar list endpoints."""

    model_config = ConfigDict(extra="forbid")

    total: int = Field(
        ...,
        description="Absolute count of matching dossiers (independent of limit/offset).",
    )
    items: list[DossierSummaryDTO]


class DossierDetailResponse(BaseModel):
    """Full dossier detail response.

    See `DossierSummaryDTO` for the semantics of `huidige_fase`,
    `stages_present`, and `titel_source`.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    kamerstuknummer: str
    titel: str | None = None
    titel_source: TitelSource | None = None
    traject_kind: TrajectKind | None = None
    huidige_fase: DossierStage | None = None
    stages_present: list[DossierStage] = Field(default_factory=list)
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
            titel_source=props.get("titel_source"),
            traject_kind=props.get("traject_kind") or "overig",
            huidige_fase=_coerce_dossier_stage(props.get("huidige_fase")),
            stages_present=_coerce_stages_list(props.get("stages_present")),
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


DossierMutationKind = Literal["mutation", "explanation"]


class DossierMutationNode(BaseModel):
    """A node in the pending-mutation subgraph."""

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
        props = doc.get("props") or {}
        raw_id = doc.get("_id", "")
        return cls(
            id=raw_id,
            key=doc.get("_key", ""),
            collection=raw_id.split("/")[0] if "/" in raw_id else "",
            type=doc.get("type", ""),
            display_name=props.get("display_name"),
            labels=list(doc.get("labels") or []),
            kind=doc.get("_kind", "mutation"),
        )


class DossierMutationEdge(BaseModel):
    """An edge in the pending-mutation subgraph."""

    model_config = ConfigDict(extra="forbid")

    from_id: str | None
    to_id: str | None
    relation: str | None
    status: str | None
    meta: dict[str, Any] | None = None
    kind: DossierMutationKind


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
    """Parliamentary committee.

    ``type`` distinguishes standing committees ('vast'), temporary committees
    ('tijdelijk'), special committees ('bijzonder'), and parliamentary inquiry
    committees ('parlementaire_enquete'). Null when the source data doesn't
    carry a type signal — treat as 'onbekend'.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    naam: str | None = None
    afkorting: str | None = None
    slug: str | None = None
    type: str | None = None
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
            type=props.get("type"),
            active_dossier_count=active_dossier_count,
        )


class FractieDTO(BaseModel):
    """Parliamentary party (fractie) summary."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    naam: str | None = None
    afkorting: str | None = None
    aliases: list[str] = []
    actief: bool = True
    aantal_zetels: int | None = None
    datum_actief: str | None = None
    datum_inactief: str | None = None
    member_count: int = 0

    @classmethod
    def from_document(cls, doc: dict[str, Any], *, member_count: int = 0) -> FractieDTO:
        props = doc.get("props") or {}
        actief = bool(props.get("actief", True))
        aantal_zetels = props.get("aantal_zetels")
        # Active fracties must have an explicit seat count; default to 0 rather
        # than null so API consumers can always compare numerically.
        if actief and aantal_zetels is None:
            aantal_zetels = 0
        return cls(
            id=doc["_id"],
            key=doc["_key"],
            naam=props.get("naam"),
            afkorting=props.get("afkorting"),
            aliases=list(props.get("aliases") or []),
            actief=actief,
            aantal_zetels=aantal_zetels,
            datum_actief=props.get("datum_actief"),
            datum_inactief=props.get("datum_inactief"),
            member_count=member_count,
        )


class FractieMembershipDTO(BaseModel):
    """One [van, tot_en_met] interval of a Lid's membership of a Fractie."""

    model_config = ConfigDict(extra="forbid")

    fractie_id: str
    fractie_key: str
    naam: str | None = None
    afkorting: str | None = None
    aliases: list[str] = []
    van: str | None = None
    tot_en_met: str | None = None
    functie: str | None = None


class LidDTO(BaseModel):
    """Parliamentary member or minister.

    ``actief`` is true when the lid has at least one open fractielidmaatschap
    (``tot_en_met`` is null) — i.e. currently seated. ~150 of ~800 ever-MPs
    qualify. ``partij`` is derived from the most recent (or currently open)
    fractielidmaatschap afkorting, so it is consistent with the
    ``fractielidmaatschappen`` list.

    ``geldig_van`` / ``geldig_tot`` are only populated when the lid is
    returned as part of a commissie query (GET /api/commissies/{slug} or
    /api/commissies/with-leden); they carry the LID_VAN edge metadata for
    that commissie. They are always null from GET /api/leden.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    naam: str | None = None
    partij: str | None = None
    actief: bool = False
    fractielidmaatschappen: list[FractieMembershipDTO] = []
    geldig_van: str | None = None
    geldig_tot: str | None = None

    @classmethod
    def from_document(cls, doc: dict[str, Any]) -> LidDTO:
        props = doc.get("props") or {}
        memberships = [
            FractieMembershipDTO(**m)
            for m in (props.get("fractielidmaatschappen") or [])
        ]
        # Derive actief: currently seated = has open membership
        open_memberships = [m for m in memberships if m.tot_en_met is None]
        actief = bool(open_memberships)

        # Derive partij: prefer open membership, else most recent by van date
        current = (
            open_memberships[-1]
            if open_memberships
            else (max(memberships, key=lambda m: m.van or "") if memberships else None)
        )
        if current:
            derived_partij = (
                current.afkorting
                if current.afkorting and current.afkorting != current.naam
                else current.naam
            )
        else:
            derived_partij = None
        partij = derived_partij or props.get("partij")

        return cls(
            id=doc["_id"],
            key=doc["_key"],
            naam=props.get("naam"),
            partij=partij,
            actief=actief,
            fractielidmaatschappen=memberships,
            geldig_van=doc.get("geldig_van"),
            geldig_tot=doc.get("geldig_tot"),
        )


class CommissieWithLedenDTO(CommissieDTO):
    """Commissie + its members. Served by GET /api/commissies/with-leden.

    Lean variant of CommissieDetailDTO: no dossiers payload, since the
    Lagen view only needs the leden halo around each committee.
    """

    model_config = ConfigDict(extra="forbid")

    leden: list[LidDTO] = []

    @classmethod
    def from_document(
        cls, doc: dict[str, Any], *, active_dossier_count: int = 0
    ) -> CommissieWithLedenDTO:
        props = doc.get("props") or {}
        leden = [LidDTO.from_document(lid) for lid in doc.get("leden") or []]
        return cls(
            id=doc["_id"],
            key=doc["_key"],
            naam=props.get("naam"),
            afkorting=props.get("afkorting"),
            slug=props.get("slug"),
            type=props.get("type"),
            active_dossier_count=props.get("active_dossier_count") if props.get("active_dossier_count") is not None else active_dossier_count,
            leden=leden,
        )


class CommissieDetailDTO(CommissieDTO):
    """Committee detail. Served by GET /api/commissies/{slug}."""

    model_config = ConfigDict(extra="forbid")

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
            type=props.get("type"),
            active_dossier_count=sum(1 for d in dossiers if not d.afgedaan),
            leden=leden,
            dossiers=dossiers,
        )


class FractieZetelDTO(BaseModel):
    """A fractie's current seat allocation, for the hemicycle view."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    afkorting: str | None
    naam: str | None
    aantal_zetels: int
    color: str | None
    order: int


class ParlementZetelsResponse(BaseModel):
    """Current seat composition of the Tweede Kamer."""

    model_config = ConfigDict(extra="forbid")

    total_seats: int
    assigned_seats: int
    as_of: str
    fracties: list[FractieZetelDTO]


class PartyColorsResponse(BaseModel):
    """Party abbreviation → hex color map for the frontend."""

    model_config = ConfigDict(extra="forbid")

    colors: dict[str, str]


# ── Search schemas ────────────────────────────────────────────────────────────

SEARCH_TYPES = frozenset(
    {
        "articles",
        "instruments",
        "judgments",
        "dossiers",
        "publications",
        "commissies",
        "leden",
        "fracties",
    }
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


class GlobalGraphResponse(BaseModel):
    """Response for GET /api/graph/global."""

    model_config = ConfigDict(extra="forbid")

    instruments: list[InstrumentLayerInstrumentDTO]
    articles: list[ArticleGraphNodeDTO]
    judgments: list[JudgmentGraphNodeDTO]
    edges: list[GraphEdgeDTO]
    metadata: dict[str, Any] | None = None


class JudgmentLayerGraphResponse(BaseModel):
    """Response for GET /api/graph/judgments."""

    model_config = ConfigDict(extra="forbid")

    judgments: list[JudgmentGraphNodeDTO]
    instruments: list[InstrumentLayerInstrumentDTO]
    edges: list[InstrumentEdgeDTO]
    metadata: dict[str, Any] | None = None


class PublicationSummary(BaseModel):
    """Lightweight publication row for the publications index page."""

    model_config = ConfigDict(extra="forbid")

    key: str
    title: str | None = None
    soort: str | None = None
    datum: str | None = None
    external_id: str | None = None
    source: str | None = None
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

    @classmethod
    def from_document(cls, doc: dict[str, Any]) -> PublicationTextResponse:
        """Build from a raw ArangoDB publication document."""
        from lawgraph.config.settings import TK_DOCUMENT_RESOURCE_URL
        from lawgraph.core.time import strip_time_component

        props: dict[str, Any] = doc.get("props") or {}
        external_id: str | None = props.get("external_id")
        tk_url = (
            TK_DOCUMENT_RESOURCE_URL.format(external_id=external_id)
            if external_id and props.get("source") == "tk"
            else None
        )
        datum: str | None = props.get("datum")
        if datum is None:
            raw = props.get("raw") or {}
            datum = raw.get("Datum")
        datum = strip_time_component(datum)
        return cls(
            key=doc["_key"],
            publication_id=doc["_id"],
            title=props.get("title"),
            soort=props.get("soort"),
            datum=datum,
            external_id=external_id,
            tk_url=tk_url,
            text=props.get("text"),
        )


class InstrumentStatsDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    by_kind: dict[str, int] = {}
    by_jurisdiction: dict[str, int] = {}


class StatsResponse(BaseModel):
    """Database statistics: document counts per collection and edge counts."""

    model_config = ConfigDict(extra="forbid")

    nodes: dict[str, int]
    edges: EdgeStatsDTO
    by_source: dict[str, dict[str, int]] = {}
    instruments: InstrumentStatsDTO = InstrumentStatsDTO()

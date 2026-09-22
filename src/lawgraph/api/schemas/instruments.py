"""Instrument endpoints: articles, citations, judgments, dossiers, related instruments,
lists, versions and cross-law dependencies."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from lawgraph.api.schemas.annexes import AnnexListItem
from lawgraph.api.schemas.common import (
    ArticleRelationDTO,
    DossierRefDTO,
    JudgmentSummaryDTO,
)
from lawgraph.config.constants import (
    EDGE_SOURCE_BWB_IMPLEMENTS,
    RELATION_IMPLEMENTS,
    RELATION_REFERS_TO,
)

# What `bwb_id` holds in the answer of an instrument route: the identifier of the request.
_REQUESTED = (
    "The instrument as requested: its BWB id, or its CELEX number for an EU act."
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
    celex: str | None = None
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
            celex=props.get("celex"),
            article_number=props.get("article_number"),
            display_name=props.get("display_name"),
            breadcrumb=crumbs,
            stub=bool(props.get("stub", False)),
            text_preview=(text[:text_preview_chars] if text else None),
        )


class InstrumentArticlesResponse(BaseModel):
    """Response for GET /api/instruments/{bwb_id}/articles."""

    model_config = ConfigDict(extra="forbid")

    bwb_id: str = Field(..., description=_REQUESTED)
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
    relation: str = Field(..., description="Edge relation type, e.g. REFERS_TO")
    direction: Literal["in", "out", "intra"] = Field(
        ...,
        description=(
            "Relative to the focal instrument: ``out`` = source is in this "
            "instrument, ``in`` = target is in it, ``intra`` = both sides."
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

    bwb_id: str = Field(..., description=_REQUESTED)
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
            "(e.g. ``{'judgments': [...], 'articles': [...]}``)."
        ),
    )


# ── /api/instruments/{bwb_id}/judgments ───────────────────────────────────


class CitedArticleRef(BaseModel):
    """Reference to one cited article inside a judgment-citation list."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(
        ...,
        description="ArangoDB document _id, e.g. ``articles/bwbr0001854_287``.",
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

    bwb_id: str = Field(..., description=_REQUESTED)
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
    """One parliamentary dossier touching this instrument."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    dossier_number: str | None = None
    title: str | None = None
    display_name: str | None = None
    stage: str | None = None
    opened_on: str | None = None
    closed: bool | None = None
    via: Literal["instrument", "amending_publication"] = Field(
        "instrument",
        description=(
            "How the dossier is linked: ``instrument`` = LEGISLATED_IN from the "
            "regulation itself, ``amending_publication`` = LEGISLATED_IN from a "
            "publication that amends, introduces or repeals one of its articles."
        ),
    )
    publication: str | None = Field(
        None,
        description=(
            "Identifier (e.g. ``stb-2019-33``) of the newest amending publication "
            "linking the dossier; only set when ``via`` is ``amending_publication``."
        ),
    )


class InstrumentDossiersResponse(BaseModel):
    """Response for GET /api/instruments/{bwb_id}/dossiers."""

    model_config = ConfigDict(extra="forbid")

    bwb_id: str = Field(..., description=_REQUESTED)
    total: int = Field(
        ...,
        description=(
            "Absolute number of dossiers touching this instrument "
            "(independent of ``limit``)."
        ),
    )
    items: list[InstrumentDossierItem]


# ── /api/instruments/{bwb_id}/amended-by ──────────────────────────────────


class AmendingInstrumentDTO(BaseModel):
    """An amending publication (Stb, Trb, ...) and what it did to a regulation."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    identifier: str = Field(..., description="Publication id, e.g. ``stb-2019-33``.")
    display_name: str | None = None
    kind: str | None = None
    year: int | None = None
    number: str | None = None
    date_signed: str | None = None
    date_published: str | None = None
    dossiers: list[DossierRefDTO] = Field(default_factory=list)
    amends: int = Field(0, description="Number of AMENDS edges into the regulation.")
    introduces: int = Field(
        0, description="Number of INTRODUCES edges into the regulation."
    )
    repeals: int = Field(0, description="Number of REPEALS edges into the regulation.")
    articles_affected: int = Field(
        0, description="Distinct articles of the regulation touched."
    )
    first_effective_date: str | None = Field(
        None, description="Earliest effective date over the edges."
    )

    @classmethod
    def from_row(
        cls, row: dict[str, Any], titles: dict[str, str | None]
    ) -> AmendingInstrumentDTO:
        """Build from an ``{instrument, amends, introduces, ...}`` query row."""
        doc = row.get("instrument") or {}
        props = doc.get("props") or {}
        year = props.get("publication_year")
        number = props.get("publication_number")
        return cls(
            id=doc.get("_id") or "",
            key=doc.get("_key") or "",
            identifier=props.get("identifier") or doc.get("_key") or "",
            display_name=props.get("display_name"),
            kind=props.get("publication_kind"),
            year=year if isinstance(year, int) else None,
            number=str(number) if number is not None else None,
            date_signed=props.get("date_signed"),
            date_published=props.get("date_published"),
            dossiers=[
                DossierRefDTO.from_number(n, titles)
                for n in props.get("dossier_numbers") or []
                if n is not None and str(n).strip()
            ],
            amends=int(row.get("amends") or 0),
            introduces=int(row.get("introduces") or 0),
            repeals=int(row.get("repeals") or 0),
            articles_affected=int(row.get("articles_affected") or 0),
            first_effective_date=row.get("first_effective_date"),
        )


class AmendedByResponse(BaseModel):
    """Response for GET /api/instruments/{bwb_id}/amended-by."""

    model_config = ConfigDict(extra="forbid")

    bwb_id: str = Field(..., description=_REQUESTED)
    total: int = Field(
        ...,
        description=(
            "Absolute number of amending instruments (independent of "
            "``limit``/``offset``)."
        ),
    )
    items: list[AmendingInstrumentDTO]


# ── /api/instruments/{bwb_id}/related-instruments ─────────────────────────


class InstrumentRelatedItem(BaseModel):
    """One other instrument linked via cross-article REFERS_TO edges."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    bwb_id: str | None = None
    celex: str | None = None
    display_name: str | None = None
    citation_title: str | None = None
    outbound_count: int = Field(
        ...,
        description=(
            "Number of REFERS_TO edges from articles of the focal "
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

    bwb_id: str = Field(..., description=_REQUESTED)
    total: int = Field(
        ...,
        description=(
            "Absolute number of related instruments (independent of ``limit``)."
        ),
    )
    items: list[InstrumentRelatedItem]


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
    state_url: str | None = None
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
            state_url=props.get("state_url"),
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


class InstrumentArticlesAtResponse(BaseModel):
    """Articles of an instrument as-of a specific date."""

    model_config = ConfigDict(extra="forbid")

    bwb_id: str
    at_date: str
    total: int
    items: list[InstrumentArticleVersionDTO]


class SharedAnnexesResponse(BaseModel):
    """Response for GET /api/instruments/{bwb_id}/shared-annexes."""

    model_config = ConfigDict(extra="forbid")

    bwb_id: str
    annexes: list[AnnexListItem] = Field(default_factory=list)


class CrossLawDependencyItem(BaseModel):
    """An article reference crossing a law boundary."""

    model_config = ConfigDict(extra="forbid")

    source_article: ArticleRelationDTO
    target_article: ArticleRelationDTO
    semantic_type: str | None = None
    explanation: str | None = None
    confidence: float | None = None


class CrossLawDependenciesResponse(BaseModel):
    """Response for GET /api/instruments/{bwb_id}/cross-law-dependencies."""

    model_config = ConfigDict(extra="forbid")

    bwb_id: str = Field(..., description=_REQUESTED)
    dependencies: list[CrossLawDependencyItem] = Field(default_factory=list)


# ── /api/instruments/{identifier} and /eu-links ───────────────────────────


class InstrumentDetailDTO(BaseModel):
    """One instrument: its identifiers, names, classification and dates."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    collection: str = "instruments"
    bwb_id: str | None = Field(
        None,
        description=(
            "BWB id of a Dutch regulation or treaty; `ECHR-CONVENTION` for the "
            "Convention of the ECHR."
        ),
    )
    celex: str | None = Field(None, description="CELEX number of an EU act.")
    title: str | None
    official_title: str | None
    citation_title: str | None
    short_title: str | None
    display_name: str | None
    jurisdiction: str | None = Field(
        None, description="`nl`, `eu` or `int` (Verdragenbank treaties)."
    )
    kind: str | None = Field(
        None,
        description=(
            "BWB type (`wet`, `AMvB`, `verdrag`, ...), treaty kind or publication kind."
        ),
    )
    source: str | None = Field(
        None, description="The source that created the node (`bwb`, `eurlex`, ...)."
    )
    labels: list[str] = Field(default_factory=list)
    lang: str | None = None
    stub: bool = False
    article_count: int = 0
    inbound_citation_count: int = 0
    date_signed: str | None = None
    date_published: str | None = None
    date_in_force: str | None = None
    treaty_number: str | None = None
    in_force: bool | None = None
    dossier_numbers: list[str] = Field(default_factory=list)

    @classmethod
    def from_document(cls, doc: dict[str, Any]) -> InstrumentDetailDTO:
        props = doc.get("props") or {}
        return cls(
            id=doc["_id"],
            key=doc["_key"],
            bwb_id=props.get("bwb_id"),
            celex=props.get("celex"),
            title=props.get("title"),
            official_title=props.get("official_title"),
            citation_title=props.get("citation_title"),
            short_title=props.get("short_title"),
            display_name=props.get("display_name"),
            jurisdiction=props.get("jurisdiction") or None,
            kind=props.get("kind"),
            source=props.get("source"),
            labels=list(doc.get("labels") or []),
            lang=props.get("lang"),
            stub=bool(props.get("stub")),
            article_count=int(props.get("article_count") or 0),
            inbound_citation_count=int(props.get("inbound_citation_count") or 0),
            date_signed=props.get("date_signed"),
            date_published=props.get("date_published"),
            date_in_force=props.get("date_in_force"),
            treaty_number=props.get("treaty_number") or None,
            in_force=props.get("in_force"),
            dossier_numbers=[str(n) for n in props.get("dossier_numbers") or []],
        )


class LinkedInstrumentDTO(BaseModel):
    """The instrument at the other end of a link."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    bwb_id: str | None
    celex: str | None
    title: str | None
    citation_title: str | None
    kind: str | None
    jurisdiction: str | None

    @classmethod
    def from_document(cls, doc: dict[str, Any]) -> LinkedInstrumentDTO:
        props = doc.get("props") or {}
        return cls(
            id=doc["_id"],
            key=doc["_key"],
            bwb_id=props.get("bwb_id"),
            celex=props.get("celex"),
            title=props.get("title") or props.get("display_name"),
            citation_title=props.get("citation_title"),
            kind=props.get("kind"),
            jurisdiction=props.get("jurisdiction") or None,
        )


# What an IMPLEMENTS edge rests on, by the pipeline that wrote it.
IMPLEMENTS_BASES: dict[str, Literal["celex_named_in_text"]] = {
    EDGE_SOURCE_BWB_IMPLEMENTS: "celex_named_in_text"
}


class EuLinkDTO(BaseModel):
    """An `IMPLEMENTS` edge between a national regulation and an EU act.

    The edge means that the text of the regulation names the CELEX number of the EU act
    (`basis`). It does not say that the regulation transposes the act, nor which articles
    do: it links instruments, not articles, and its `confidence` is that of a text match.
    """

    model_config = ConfigDict(extra="forbid")

    instrument: LinkedInstrumentDTO = Field(
        ...,
        description=(
            "The other end: the EU act for `implements`, the national regulation for "
            "`implemented_by`."
        ),
    )
    relation: str = RELATION_IMPLEMENTS
    confidence: float | None = None
    basis: Literal["celex_named_in_text"] | None = Field(
        None,
        description=(
            "What the edge rests on: `celex_named_in_text`, the text of the regulation "
            "names the CELEX number of the act. Not a transposition signal."
        ),
    )
    source: str | None = Field(
        None,
        description="The pipeline that wrote the edge (`bwb-implements-directive`).",
    )
    meta: dict[str, Any] = Field(
        default_factory=dict, description="Edge evidence as stored (`celex`)."
    )

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> EuLinkDTO:
        """Build from an ``{instrument, edge}`` query row."""
        edge = row.get("edge") or {}
        return cls(
            instrument=LinkedInstrumentDTO.from_document(row["instrument"]),
            confidence=edge.get("confidence"),
            basis=IMPLEMENTS_BASES.get(edge.get("source") or ""),
            source=edge.get("source"),
            meta=edge.get("meta") or {},
        )


class InternationalLinkDTO(BaseModel):
    """A `REFERS_TO` edge between this instrument and an international counterpart.

    `treaty`: an article of this instrument (`own_article`) refers to a treaty
    (`instrument`), and to a treaty article (`counterpart_article`) when the reference names
    one. `echr_judgment`: an ECHR judgment (`judgment`) refers to an article of this
    instrument (`own_article`) or, without an article, to the instrument as a whole.
    """

    model_config = ConfigDict(extra="forbid")

    kind: Literal["treaty", "echr_judgment"]
    instrument: LinkedInstrumentDTO | None = Field(
        None, description="The treaty; set for `treaty`."
    )
    judgment: JudgmentSummaryDTO | None = Field(
        None, description="The ECHR judgment; set for `echr_judgment`."
    )
    own_article: CitedArticleRef | None = Field(
        None, description="The article of this instrument at the edge, when it has one."
    )
    counterpart_article: CitedArticleRef | None = Field(
        None, description="The article of the treaty the reference names."
    )
    relation: str = RELATION_REFERS_TO
    confidence: float | None = None
    source: str | None = Field(None, description="The pipeline that wrote the edge.")
    meta: dict[str, Any] = Field(
        default_factory=dict,
        description="Edge evidence as stored (`raw_match`, `snippet`, `qualifier`, ...).",
    )


class InstrumentEuLinksResponse(BaseModel):
    """Response for GET /api/instruments/{identifier}/eu-links."""

    model_config = ConfigDict(extra="forbid")

    instrument: LinkedInstrumentDTO
    implements: list[EuLinkDTO] = Field(
        default_factory=list,
        description="EU acts whose CELEX number the text of this instrument names.",
    )
    implements_total: int = Field(
        ..., description="Absolute number of `implements`, independent of `limit`."
    )
    implemented_by: list[EuLinkDTO] = Field(
        default_factory=list,
        description="National regulations whose text names the CELEX number of this act.",
    )
    implemented_by_total: int = Field(
        ..., description="Absolute number of `implemented_by`, independent of `limit`."
    )
    international: list[InternationalLinkDTO] = Field(
        default_factory=list,
        description=(
            "Treaties that articles of this instrument refer to and ECHR judgments that "
            "refer to it, at most `limit`, treaties first."
        ),
    )
    international_total: int = Field(
        ..., description="Absolute number of `international`, independent of `limit`."
    )

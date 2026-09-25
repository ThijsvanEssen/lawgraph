"""Article endpoints: detail, relationships, legislative history, explanatory
documents, version history and in-flux state."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from lawgraph.api.schemas.common import (
    ARTICLE_ADDRESS,
    ArticleCitationSpan,
    ArticleRelationDTO,
    InstrumentSummaryDTO,
    JudgmentSummaryDTO,
    PublicationDTO,
    QualifierFields,
    address_of,
)
from lawgraph.api.schemas.documents import DocumentOrigin, origin_fields
from lawgraph.config.constants import (
    COLLECTION_ARTICLE_VERSIONS,
    COLLECTION_ARTICLES,
    COLLECTION_INSTRUMENTS,
)
from lawgraph.core.bwb_xml import effect_kind
from lawgraph.core.mentions import Mention
from lawgraph.core.models import parse_arango_id
from lawgraph.core.official_urls import article_url
from lawgraph.core.qualifiers import Qualifier
from lawgraph.core.time import strip_time_component

ExplanationTarget = Literal["article", "article_version", "instrument"]
ExplanationScope = Literal["dossier", "article"]

_TARGET_OF_COLLECTION: dict[str, ExplanationTarget] = {
    COLLECTION_ARTICLES: "article",
    COLLECTION_ARTICLE_VERSIONS: "article_version",
    COLLECTION_INSTRUMENTS: "instrument",
}


class ArticlePartDTO(BaseModel):
    """A lid, an onderdeel or an aanhef of an article, as a span of its `text`."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(
        description="Where the part sits: `aanhef`, `lid-2`, `lid-2-aanhef`, `lid-2-onder-a`, "
        "`onder-a` (an article without leden), `lid-2-onder-a-onder-1` (an onderdeel "
        "inside an onderdeel). Unique within the article."
    )
    kind: str = Field(description="`aanhef`, `lid` or `onderdeel`.")
    number: str | None = Field(
        description="The number as printed: `2`, `2a`, `a`, `1°`; null for an aanhef "
        "or an item without one."
    )
    text: str = Field(
        description="The content without its number: `text[start:end]` of the article. "
        "A part with onderdelen spans them too."
    )
    start: int = Field(description="Offset of the part in the `text` of the article.")
    end: int


def parts_from_props(props: dict[str, Any]) -> list[ArticlePartDTO]:
    """The parts stored on an article or version, with their text cut from `props.text`.

    Entries that do not fit the text are left out rather than failing the response.
    """
    text = props.get("text")
    stored = props.get("parts")
    if not isinstance(text, str) or not isinstance(stored, list):
        return []
    parts: list[ArticlePartDTO] = []
    for part in stored:
        if not isinstance(part, dict):
            continue
        start, end = part.get("start"), part.get("end")
        if not (
            isinstance(start, int)
            and isinstance(end, int)
            and 0 <= start < end <= len(text)
        ):
            continue
        parts.append(
            ArticlePartDTO(
                id=str(part.get("id") or ""),
                kind=str(part.get("kind") or ""),
                number=part.get("number"),
                text=text[start:end],
                start=start,
                end=end,
            )
        )
    return parts


class ArticleReferenceDTO(QualifierFields):
    """A reference the text of an article makes to an article of a regulation."""

    kind: str = Field(
        description="`intref` (a link inside the regulation) or `extref` (to another)."
    )
    bwb_id: str | None
    article: str | None = Field(
        description="Number of the article referred to; null for a reference to a chapter "
        "or a title."
    )
    doc: str = Field(description="The JCI string of the link, as the XML has it.")
    text: str
    start: int = Field(description="Offset of `text` in the text of the article.")
    end: int


def references_from_props(props: dict[str, Any]) -> list[ArticleReferenceDTO]:
    """The references stored on an article, in text order, resolvable or not."""
    stored = props.get("references")
    if not isinstance(stored, list):
        return []
    references = [
        ArticleReferenceDTO(
            kind=str(ref.get("kind") or ""),
            bwb_id=ref.get("bwb_id"),
            article=ref.get("article"),
            doc=str(ref.get("doc") or ""),
            text=str(ref.get("text") or ""),
            start=int(ref.get("start") or 0),
            end=int(ref.get("end") or 0),
            **Qualifier.from_dict(ref).to_dict(),
        )
        for ref in stored
        if isinstance(ref, dict)
    ]
    return sorted(references, key=lambda ref: (ref.start, ref.end))


class ArticleSummaryDTO(BaseModel):
    """Summary of an article: its identifiers and text."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    bwb_id: str | None
    article_number: str | None = Field(
        None,
        description="Null for an article with only a heading, and for a repealed one.",
    )
    label: str | None = Field(
        None,
        description="`Artikel 287`, or the heading of an article without a number "
        "(`Algemene bepaling`).",
    )
    heading: str | None = Field(
        None,
        description="The title of its kop (`Definities`); most articles have none.",
    )
    address: str = Field(..., description=ARTICLE_ADDRESS)
    repealed: bool = False
    display_name: str | None
    official_url: str | None = Field(
        None,
        description="The article in force on wetten.overheid.nl (its JCI); the "
        "regulation for an article without a number the JCI can address.",
    )
    text: str | None
    parts: list[ArticlePartDTO] = Field(
        default_factory=list,
        description="Aanhef, leden and onderdelen as spans of `text`; empty when the "
        "article has no structure or was normalized before parts existed.",
    )

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
            label=props.get("label"),
            heading=props.get("heading"),
            address=address_of(doc),
            repealed=bool(props.get("repealed")),
            display_name=props.get("display_name"),
            official_url=article_url(props.get("bwb_id"), props.get("article_number")),
            text=props.get("text"),
            parts=parts_from_props(props),
        )


class ArticleRelationshipWithType(QualifierFields):
    """An article-to-article relationship enriched with its semantic layer."""

    model_config = ConfigDict(extra="forbid")

    edge_id: str
    relation: str
    target_article: ArticleRelationDTO
    semantic_type: str | None = None
    explanation: str | None = None
    confidence: float | None = None
    start: int | None = Field(
        None,
        description="Offset of the reference in the text of the referring article.",
    )
    end: int | None = None
    text: str | None = Field(None, description="The text of the reference.")
    reference_kind: str | None = Field(
        default=None, description="`intref` or `extref`, as on the reference itself."
    )

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> ArticleRelationshipWithType:
        """Build from a {edge, target, instrument} query row."""
        edge = row.get("edge") or {}
        meta: dict[str, Any] = edge.get("meta") or {}
        start, end, text = meta.get("start"), meta.get("end"), meta.get("text")
        return cls(
            edge_id=edge.get("_key") or "",
            relation=edge.get("relation") or "",
            target_article=ArticleRelationDTO.from_documents(
                row["target"], row.get("instrument")
            ),
            semantic_type=edge.get("semantic_type"),
            explanation=edge.get("explanation"),
            confidence=edge.get("confidence"),
            start=start if isinstance(start, int) else None,
            end=end if isinstance(end, int) else None,
            text=text if isinstance(text, str) else None,
            reference_kind=meta.get("reference_kind"),
            **Qualifier.from_dict(meta).to_dict(),
        )


class ScopeArticleReference(BaseModel):
    """Annex that scopes the applicability of an article."""

    model_config = ConfigDict(extra="forbid")

    annex_id: str
    annex_key: str
    display_name: str | None = None
    annex_entries: list[str] = Field(default_factory=list)
    scope_type: str = "fixed"
    discretionary_authority_article: str | None = None
    explanation: str | None = None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> ScopeArticleReference:
        """Build from an {edge, annex} query row."""
        edge = row.get("edge") or {}
        meta = edge.get("meta") or {}
        annex = row.get("annex") or {}
        props = annex.get("props") or {}
        entries = [
            str(e.get("name"))
            for e in (props.get("entries") or [])
            if isinstance(e, dict) and e.get("name")
        ]
        return cls(
            annex_id=annex.get("_id") or "",
            annex_key=annex.get("_key") or "",
            display_name=props.get("display_name"),
            annex_entries=entries,
            scope_type=meta.get("scope_type") or "fixed",
            discretionary_authority_article=meta.get("discretionary_authority_article"),
            explanation=edge.get("explanation"),
        )


class ArticleRelationshipsResponse(BaseModel):
    """Response for GET /api/articles/{bwb_id}/{article_number}/relationships."""

    model_config = ConfigDict(extra="forbid")

    article_id: str
    upstream_dependencies: list[ArticleRelationshipWithType] = Field(
        default_factory=list
    )
    downstream_implications: list[ArticleRelationshipWithType] = Field(
        default_factory=list
    )
    scope_articles: list[ScopeArticleReference] = Field(default_factory=list)


class ArticleDetailResponse(BaseModel):
    """Response for GET /api/articles/{bwb_id}/{article_number}."""

    model_config = ConfigDict(extra="forbid")

    article: ArticleSummaryDTO
    instrument: InstrumentSummaryDTO | None
    judgments: list[JudgmentSummaryDTO]
    citations: list[ArticleCitationSpan] = Field(default_factory=list)
    references: list[ArticleReferenceDTO] = Field(
        default_factory=list,
        description="Every reference the text of the article makes, as stored on it, "
        "whether or not the target is in the graph. `citations` holds the resolved ones, "
        "one per target.",
    )
    metadata: dict[str, Any] | None
    upstream_dependencies: list[ArticleRelationshipWithType] = Field(
        default_factory=list
    )
    downstream_implications: list[ArticleRelationshipWithType] = Field(
        default_factory=list
    )
    scope_articles: list[ScopeArticleReference] = Field(default_factory=list)


class CitedByJudgment(BaseModel):
    """The judgment of a passage that cites an article."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    ecli: str | None
    court: str | None = Field(description="ECLI court code, `HR`, `RBAMS`.")
    tier: str | None = Field(
        description="The college: `hoge_raad`, `raad_van_state`, `centrale_raad_van_beroep`, "
        "`college_van_beroep_bedrijfsleven`, `parket`, `gerechtshof`, `rechtbank`, … "
        "(`/api/stats/coverage` lists those present).",
    )
    date: str | None = Field(description="Date of the judgment, YYYY-MM-DD.")
    display_name: str | None


class ArticleCitedByItem(QualifierFields):
    """One passage of a judgment that cites the article. `leden`, `onderdelen` and
    `aanhef` say what the passage names of it."""

    judgment: CitedByJudgment
    paragraph_id: str = Field(
        description="The paragraph, as `paragraph_id` of `/api/judgments/{ecli}`."
    )
    paragraph_number: str | None = Field(
        description="Its printed number (`5.3`), null when it has none."
    )
    qualifier: str | None = Field(
        description="The qualifier as the judgment wrote it, `derde lid`."
    )
    start: int = Field(
        description="Offset of the citation in the text of the paragraph."
    )
    end: int
    text: str = Field(description="The citation as written: `text[start:end]`.")
    snippet: str = Field(description="The text of the paragraph around the citation.")
    confidence: float

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> ArticleCitedByItem | None:
        """Build from a `{judgment, mention}` row; None when the mention is malformed."""
        mention = Mention.from_dict(row.get("mention"))
        if mention is None:
            return None
        doc = row["judgment"]
        props = doc.get("props") or {}
        return cls(
            judgment=CitedByJudgment(
                id=doc["_id"],
                key=doc["_key"],
                ecli=props.get("ecli"),
                court=props.get("court_code"),
                tier=props.get("tier"),
                date=props.get("date_eff"),
                display_name=props.get("display_name"),
            ),
            paragraph_id=mention.paragraph_id,
            paragraph_number=mention.paragraph_number,
            qualifier=mention.qualifier,
            start=mention.start,
            end=mention.end,
            text=mention.raw_match,
            snippet=mention.snippet,
            confidence=mention.confidence,
            **mention.parts.to_dict(),
        )


class ArticleCitedByResponse(BaseModel):
    """Response for GET /api/articles/{bwb_id}/{article_number}/cited-by."""

    model_config = ConfigDict(extra="forbid")

    article_id: str
    items: list[ArticleCitedByItem]
    total: int = Field(
        description="Every passage that matches the filters, independent of `limit`."
    )


class LegislativeHistoryEntry(BaseModel):
    """One change of an article in one dossier: the dossier, and the amending publication
    (enacted) or the bill (proposed) that made or proposes the change."""

    model_config = ConfigDict(extra="forbid")

    dossier_id: str | None = Field(
        None,
        description="Arango _id of the dossier; null when the publication names a dossier "
        "that is not in the graph.",
    )
    dossier_number: str
    dossier_title: str | None = None
    date: str | None = Field(
        None, description="Of the bill, or the publication date of the publication."
    )
    kind: str | None = Field(
        None,
        description="Document kind of a bill, publication kind (`Stb`) of a publication.",
    )
    change: Literal["amends", "introduces", "repeals"]
    status: str | None = Field(
        None, description="`canoniek` (enacted) or `voorgesteld` (proposed)."
    )
    summary: str | None = None
    document_id: str = Field(
        ..., description="Arango _id of the publication or the bill."
    )


class ArticleLegislativeHistoryResponse(BaseModel):
    """Legislative history for an article."""

    model_config = ConfigDict(extra="forbid")

    article_id: str
    entries: list[LegislativeHistoryEntry]
    total: int


class ExplainingDocumentDTO(DocumentOrigin):
    """The explanatory document of an explanation."""

    id: str = Field(..., description="Arango _id of the document.")
    key: str
    kind: str | None = None
    title: str | None = None
    date: str | None = None
    dossier_number: str | None = Field(
        None,
        description="The dossier the document is PART_OF (the lowest, if several).",
    )


class ArticleExplanationDTO(BaseModel):
    """One document that explains an article, and the node its EXPLAINS edge points at."""

    model_config = ConfigDict(extra="forbid")

    document: ExplainingDocumentDTO
    target: ExplanationTarget = Field(
        ...,
        description=(
            "What the edge points at: the 'article', one of its versions "
            "('article_version') or its 'instrument'. An 'instrument' explanation "
            "is written only when the dossier's law changed no articles at all, so "
            "it says nothing about this article in particular."
        ),
    )
    target_id: str = Field(
        ..., description="Arango _id of the node the edge points at."
    )
    article_version_key: str | None = Field(
        None,
        description="Key of the article version; null unless target is 'article_version'.",
    )
    confidence: float | None = None
    scope: ExplanationScope = Field(
        ...,
        description=(
            "'dossier': the document explains the changes of a whole dossier, not "
            "this article in particular (the memorandum is not tied to a passage). "
            "'article': the edge names the section that explains the article, "
            "in ``section_anchor``."
        ),
    )
    section_anchor: str | None = Field(
        None,
        description="`id` of the section in `sections` of the document; set when scope "
        "is 'article'.",
    )

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> ArticleExplanationDTO:
        """Build from a row of ``get_article_explanations``."""
        collection, key = parse_arango_id(row["target_id"])
        target = _TARGET_OF_COLLECTION[collection]
        section_anchor = row.get("section_anchor") or None
        return cls(
            document=ExplainingDocumentDTO(
                id=row["document_id"],
                key=row["key"],
                kind=row.get("kind") or None,
                title=row.get("title") or None,
                date=strip_time_component(row.get("date")),
                dossier_number=row.get("dossier_number"),
                **origin_fields(row.get("labels"), row.get("source"), row.get("kind")),
            ),
            target=target,
            target_id=row["target_id"],
            article_version_key=key if target == "article_version" else None,
            confidence=row.get("confidence"),
            scope="article" if section_anchor else "dossier",
            section_anchor=section_anchor,
        )


class ArticleExplanationsResponse(BaseModel):
    """Response for GET /api/articles/{bwb_id}/{article_number}/explained-by."""

    model_config = ConfigDict(extra="forbid")

    article_id: str
    total: int = Field(
        ..., description="All explanations, independent of ``limit`` and ``offset``."
    )
    items: list[ArticleExplanationDTO]


class ArticleInFluxResponse(BaseModel):
    """In-flux status for an article."""

    model_config = ConfigDict(extra="forbid")

    article_id: str
    in_flux: bool
    open_dossier_count: int


class ArticleVersionDTO(BaseModel):
    """One dated version of an article, with the publication that produced it."""

    model_config = ConfigDict(extra="forbid")

    key: str
    article_number: str | None = None
    label: str | None = Field(
        None,
        description="`Artikel 287`, or the heading of an article without a number.",
    )
    valid_from: str | None = None
    valid_until: str | None = None
    current: bool = False
    official_url: str | None = Field(
        None,
        description="This version on wetten.overheid.nl: the JCI with ``g`` its "
        "``valid_from``.",
    )
    text: str | None = None
    parts: list[ArticlePartDTO] = Field(
        default_factory=list, description="As on the article: spans of `text`."
    )
    effect: str | None = Field(None, description="Raw BWB effect of this version.")
    change: str | None = Field(
        None,
        description="Normalised effect: 'introduces', 'amends', 'repeals' or null.",
    )
    source_publication: str | None = None
    amended_by: PublicationDTO | None = Field(
        None, description="Publication that created this version."
    )
    commencement: PublicationDTO | None = Field(
        None, description="Publication that brought this version into force."
    )

    @classmethod
    def from_document(
        cls, doc: dict[str, Any], titles: dict[str, str | None]
    ) -> ArticleVersionDTO:
        props = doc.get("props") or {}
        effect = props.get("effect")
        return cls(
            key=doc["_key"],
            article_number=props.get("article_number"),
            label=props.get("label"),
            valid_from=props.get("valid_from"),
            valid_until=props.get("valid_until"),
            current=bool(props.get("current", False)),
            official_url=article_url(
                props.get("bwb_id"),
                props.get("article_number"),
                on=props.get("valid_from"),
            ),
            text=props.get("text"),
            parts=parts_from_props(props),
            effect=effect,
            change=effect_kind(effect),
            source_publication=props.get("source_publication"),
            amended_by=PublicationDTO.from_dict(
                props.get("origin_publication"), titles
            ),
            commencement=PublicationDTO.from_dict(
                props.get("commencement_publication"), titles
            ),
        )


class ArticleHistoryResponse(BaseModel):
    """Response for GET /api/articles/{bwb_id}/{article_number}/history."""

    model_config = ConfigDict(extra="forbid")

    bwb_id: str
    article_number: str
    stam_id: str | None = Field(
        None, description="Stable BWB identity of the article across versions."
    )
    versions: list[ArticleVersionDTO] = Field(
        default_factory=list, description="All versions, oldest first."
    )

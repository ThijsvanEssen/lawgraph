"""Article endpoints: detail, relationships, legislative history, version history
and in-flux state."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from lawgraph.api.schemas.common import (
    ArticleCitationSpan,
    ArticleRelationDTO,
    CommunityVotes,
    InstrumentSummaryDTO,
    JudgmentSummaryDTO,
    PublicationDTO,
)
from lawgraph.core.bwb_xml import effect_kind


class ArticleSummaryDTO(BaseModel):
    """Summary of an article: its identifiers and text."""

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


class ArticleRelationshipWithType(BaseModel):
    """An article-to-article relationship enriched with its semantic layer."""

    model_config = ConfigDict(extra="forbid")

    edge_id: str
    relation: str
    target_article: ArticleRelationDTO
    semantic_type: str | None = None
    explanation: str | None = None
    expert_badge: bool = False
    semantic_source: str | None = None
    confidence: float | None = None
    community_votes: CommunityVotes = Field(default_factory=CommunityVotes)

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> ArticleRelationshipWithType:
        """Build from a {edge, target, instrument} query row."""
        edge = row.get("edge") or {}
        return cls(
            edge_id=edge.get("_key") or "",
            relation=edge.get("relation") or "",
            target_article=ArticleRelationDTO.from_documents(
                row["target"], row.get("instrument")
            ),
            semantic_type=edge.get("semantic_type"),
            explanation=edge.get("explanation"),
            expert_badge=bool(edge.get("expert_badge") or False),
            semantic_source=edge.get("semantic_source"),
            confidence=edge.get("confidence"),
            community_votes=CommunityVotes(
                upvotes=int(edge.get("community_upvotes") or 0),
                downvotes=int(edge.get("community_downvotes") or 0),
            ),
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
    metadata: dict[str, Any] | None
    upstream_dependencies: list[ArticleRelationshipWithType] = Field(
        default_factory=list
    )
    downstream_implications: list[ArticleRelationshipWithType] = Field(
        default_factory=list
    )
    scope_articles: list[ScopeArticleReference] = Field(default_factory=list)


class LegislativeHistoryEntry(BaseModel):
    """One entry in the legislative history of an article."""

    model_config = ConfigDict(extra="forbid")

    dossier_id: str | None = None
    dossier_number: str | None = None
    dossier_title: str | None = None
    date: str | None = None
    kind: str | None = None
    status: str | None = None
    summary: str | None = None
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


class ArticleVersionDTO(BaseModel):
    """One dated version of an article, with the publication that produced it."""

    model_config = ConfigDict(extra="forbid")

    key: str
    article_number: str | None = None
    valid_from: str | None = None
    valid_until: str | None = None
    current: bool = False
    text: str | None = None
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
            valid_from=props.get("valid_from"),
            valid_until=props.get("valid_until"),
            current=bool(props.get("current", False)),
            text=props.get("text"),
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

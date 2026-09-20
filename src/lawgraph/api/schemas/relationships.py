"""Semantic relationship endpoints: tagging, voting and search."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from lawgraph.api.schemas.common import ArticleRelationDTO, CommunityVotes


class RelationshipTagRequest(BaseModel):
    """Request body for POST /api/relationships/tag.

    Article references use the 'BWBR0001854/287' (bwb_id/article_number) form.
    """

    model_config = ConfigDict(extra="forbid")

    source_article: str
    target_article: str
    semantic_type: str
    explanation: str | None = None
    semantic_source: str = "expert"
    expert_badge: bool = False
    created_by: str | None = None


class RelationshipDTO(BaseModel):
    """A single semantic relationship row (tag response and search results)."""

    model_config = ConfigDict(extra="forbid")

    edge_id: str
    from_id: str
    to_id: str
    relation: str
    semantic_type: str | None = None
    explanation: str | None = None
    expert_badge: bool = False
    semantic_source: str | None = None
    confidence: float | None = None
    community_votes: CommunityVotes = Field(default_factory=CommunityVotes)
    source_article: ArticleRelationDTO | None = None
    target_article: ArticleRelationDTO | None = None

    @classmethod
    def from_edge(
        cls,
        edge: dict[str, Any],
        *,
        source_article: dict[str, Any] | None = None,
        target: dict[str, Any] | None = None,
    ) -> RelationshipDTO:
        return cls(
            edge_id=edge.get("_key") or "",
            from_id=edge.get("_from") or "",
            to_id=edge.get("_to") or "",
            relation=edge.get("relation") or "",
            semantic_type=edge.get("semantic_type"),
            explanation=edge.get("explanation"),
            expert_badge=bool(edge.get("expert_badge") or False),
            semantic_source=edge.get("semantic_source"),
            confidence=edge.get("confidence"),
            community_votes=CommunityVotes(
                upvotes=int(edge.get("community_upvotes") or 0),
                downvotes=int(edge.get("community_downvotes") or 0),
            ),
            source_article=(
                ArticleRelationDTO.from_documents(source_article, None)
                if source_article
                else None
            ),
            target_article=(
                ArticleRelationDTO.from_documents(target, None) if target else None
            ),
        )


class RelationshipVoteRequest(BaseModel):
    """Request body for POST /api/relationships/{edge_id}/vote."""

    model_config = ConfigDict(extra="forbid")

    vote: str  # 'upvote' | 'downvote'


class RelationshipVoteResponse(BaseModel):
    """Updated vote counters after a community vote."""

    model_config = ConfigDict(extra="forbid")

    edge_id: str
    community_votes: CommunityVotes


class RelationshipSearchResponse(BaseModel):
    """Paginated semantic relationship search results."""

    model_config = ConfigDict(extra="forbid")

    relationships: list[RelationshipDTO]
    total: int
    limit: int
    offset: int

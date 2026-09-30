"""Semantic relationship endpoints: search."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from lawgraph.api.schemas.common import (
    SEMANTIC_CONFIDENCE,
    SEMANTIC_PATTERN,
    ArticleRelationDTO,
    semantic_fields,
)


class RelationshipDTO(BaseModel):
    """A single semantic relationship row of the search results."""

    model_config = ConfigDict(extra="forbid")

    edge_id: str
    from_id: str
    to_id: str
    relation: str
    semantic_type: str | None = None
    explanation: str | None = Field(
        default=None,
        description="What `semantic_type` rests on: the trigger phrase and where it stood.",
    )
    confidence: float | None = Field(
        default=None,
        description="That the reference exists: 1.0 for a link of the BWB XML.",
    )
    semantic_confidence: float | None = Field(
        default=None, description=SEMANTIC_CONFIDENCE
    )
    semantic_pattern: str | None = Field(default=None, description=SEMANTIC_PATTERN)
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
            confidence=edge.get("confidence"),
            **semantic_fields(edge),
            source_article=(
                ArticleRelationDTO.from_documents(source_article, None)
                if source_article
                else None
            ),
            target_article=(
                ArticleRelationDTO.from_documents(target, None) if target else None
            ),
        )


class RelationshipSearchResponse(BaseModel):
    """Paginated semantic relationship search results."""

    model_config = ConfigDict(extra="forbid")

    relationships: list[RelationshipDTO]
    total: int
    limit: int
    offset: int

"""Judgment endpoints: detail (with inline citations) and lists."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from lawgraph.api.schemas.common import (
    ArticleCitationSpan,
    ArticleRelationDTO,
    JudgmentSummaryDTO,
)
from lawgraph.api.schemas.nodes import _DROP_PROPS_KEYS, BaseNodeDTO
from lawgraph.core.identifiers import ecli_source


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
        source = props.get("source") or ecli_source(ecli)
        return cls(
            **base.model_dump(),
            ecli=ecli,
            source=source,
            summary=props.get("summary"),
            paragraphs=paragraphs,
        )


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
        source = row.get("source") or ecli_source(ecli)
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

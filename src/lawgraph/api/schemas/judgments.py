"""Judgment endpoints: detail (with inline citations) and lists."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from lawgraph.api.schemas.common import (
    ArticleCitationSpan,
    ArticleRelationDTO,
    JudgmentSummaryDTO,
    QualifierFields,
)
from lawgraph.api.schemas.nodes import _DROP_PROPS_KEYS, BaseNodeDTO
from lawgraph.core.identifiers import ecli_source
from lawgraph.core.mentions import MAX_MENTIONS_PER_EDGE, Mention


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
        kept = [p for p in raw_paragraphs if isinstance(p, dict) and p.get("text")]
        paragraphs = [
            JudgmentParagraph(
                # A paragraph normalized before `paragraph_id` existed has no "id"; fall
                # back to its position rather than 500 the whole judgment on one stale
                # record (`core.judgments.extract_sections` uses the same "p-<n>" shape
                # for a paragraph without a printed number).
                paragraph_id=p.get("id") or f"p-{position}",
                number=p.get("number"),
                kind=p.get("kind"),
                text=p.get("text") or "",
            )
            for position, p in enumerate(kept, start=1)
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
    """A single paragraph from a judgment, with the article citations in it."""

    model_config = ConfigDict(extra="forbid")

    paragraph_id: str = Field(
        description="Names the paragraph in the judgment, for a deep link: `rov-5.3` for "
        "the numbered consideration 5.3, `kop-5` for a numbered heading, `p-12` (its "
        "position) for a paragraph without a number. Unique in the judgment."
    )
    number: str | None = Field(
        default=None,
        description="The number as printed, without its closing dot (`5.3`); not part of "
        "`text`. Null for a paragraph without one.",
    )
    kind: str | None = Field(
        default=None, description="`heading`, `subheading` or `body`."
    )
    text: str
    citations: list[ArticleCitationSpan] = Field(
        default_factory=list,
        description="Every citation of an article in `text`, one per occurrence, with its "
        "span (`text[start:end]`).",
    )


class JudgmentCitedArticle(QualifierFields):
    """An article a judgment cites, with where and how: the strongest of its mentions."""

    article: ArticleRelationDTO
    qualifier: str | None = Field(
        default=None,
        description="The qualifier as the judgment wrote it, `derde lid`, of the strongest "
        "mention. `leden`, `onderdelen` and `aanhef` (this class) are what it names.",
    )
    paragraph_ids: list[str] = Field(
        default_factory=list,
        description="The paragraphs that cite the article, in reading order.",
    )
    paragraph_numbers: list[str] = Field(
        default_factory=list,
        description="Their printed numbers (`5.3`), those that have one.",
    )
    snippet: str | None = Field(
        default=None, description="The text around the strongest mention."
    )
    confidence: float | None = Field(
        default=None, description="The confidence of the strongest mention."
    )
    mention_count: int = Field(
        default=0,
        description="How often the judgment cites the article. The paragraphs cover the "
        f"first {MAX_MENTIONS_PER_EDGE}; a judgment that cites an article more often is "
        "counted in full.",
    )

    @classmethod
    def from_relation(
        cls,
        article: ArticleRelationDTO,
        meta: dict[str, Any],
        confidence: float | None,
    ) -> JudgmentCitedArticle:
        mentions = mentions_of(meta)
        strongest = max(mentions, key=lambda m: m.confidence, default=None)
        numbers = [m.paragraph_number for m in mentions if m.paragraph_number]
        return cls(
            article=article,
            qualifier=strongest.qualifier if strongest else None,
            **(strongest.parts.to_dict() if strongest else {}),
            paragraph_ids=list(dict.fromkeys(m.paragraph_id for m in mentions)),
            paragraph_numbers=list(dict.fromkeys(numbers)),
            snippet=strongest.snippet if strongest else None,
            confidence=strongest.confidence if strongest else confidence,
            mention_count=_count(meta, mentions),
        )


def mentions_of(meta: dict[str, Any]) -> list[Mention]:
    """The stored mentions of a REFERS_TO edge from a judgment, in reading order."""
    stored = meta.get("mentions")
    if not isinstance(stored, list):
        return []
    return [m for m in map(Mention.from_dict, stored) if m is not None]


def _count(meta: dict[str, Any], mentions: list[Mention]) -> int:
    count = meta.get("mention_count")
    return count if isinstance(count, int) and count >= len(mentions) else len(mentions)


class JudgmentDetailResponse(BaseModel):
    """Response for GET /api/judgments/{ecli}."""

    model_config = ConfigDict(extra="forbid")

    judgment: JudgmentDTO
    articles: list[ArticleRelationDTO]
    cited_articles: list[JudgmentCitedArticle] = Field(
        default_factory=list,
        description="The same articles, each with the passages of the judgment that cite "
        "it: paragraphs, the lid or onderdeel named, a snippet.",
    )
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

"""The block of a concept: articles that together make one doctrine (``core.concept_articles``)
and what cites any of them."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from lawgraph.api.schemas.article_cited_by import CitedByJudgment
from lawgraph.api.schemas.articles import ExplainingDocumentDTO, passage_excerpt
from lawgraph.api.schemas.common import PathSource, StrictModel, WithPath
from lawgraph.api.schemas.documents import origin_fields
from lawgraph.core.concept_articles import Concept
from lawgraph.core.names import article_cite
from lawgraph.core.time import strip_time_component


class ConceptExplanationDTO(StrictModel):
    """An official page that explains the concept: a link, no text of ours."""

    label: str = Field(description="Who publishes it: `Rijksoverheid`.")
    url: str


class ConceptArticleDTO(WithPath):
    """One article of a concept."""

    path_source = PathSource("articles")

    id: str
    key: str
    display_name: str | None = Field(description="`Art. 120 Gw`.")
    heading: str | None = Field(
        description="Its heading in the law; null where the law gives none."
    )
    opening: str | None = Field(
        description="The start of its text, about 300 characters cut at a word (`…` "
        "when it goes on): what the block shows where the law gives no heading."
    )
    judgment_total: int = Field(description="The judgments that cite it.")

    @classmethod
    def from_doc(cls, doc: dict[str, Any], judgments: int) -> ConceptArticleDTO:
        props = doc.get("props") or {}
        return cls(
            id=doc["id"],
            key=doc["key"],
            display_name=article_cite(props) or None,
            heading=props.get("heading") or None,
            opening=passage_excerpt(props.get("text"), props.get("heading")),
            judgment_total=judgments,
            path_props=props,
        )


class ConceptJudgmentDTO(StrictModel):
    """A judgment that cites an article of the concept."""

    judgment: CitedByJudgment
    article_ids: list[str] = Field(
        description="The articles of the concept it cites (`ConceptArticleDTO.id`)."
    )


class ConceptDocumentDTO(StrictModel):
    """A paper an edge joins to an article of the concept (it explains or names it)."""

    document: ExplainingDocumentDTO
    article_ids: list[str] = Field(
        description="The articles of the concept it is joined to."
    )

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> ConceptDocumentDTO:
        numbering = row.get("paper") or {}
        sequence = numbering.get("sequence")
        number = numbering.get("dossier_number")
        return cls(
            document=ExplainingDocumentDTO(
                id=row["document_id"],
                key=row["key"],
                kind=row.get("kind") or None,
                title=row.get("title") or None,
                date=strip_time_component(row.get("date")),
                dossier_number=str(number) if number is not None else None,
                sequence=sequence if isinstance(sequence, int) else None,
                path_props=numbering,
                **origin_fields(row.get("labels"), row.get("source"), row.get("kind")),
            ),
            article_ids=list(row.get("article_ids") or []),
        )


class ConceptResponse(StrictModel):
    """Response for GET /api/concepts/{key}."""

    key: str
    name: str
    explanation: ConceptExplanationDTO | None = Field(
        description="An official page that explains it; null where none is kept."
    )
    articles: list[ConceptArticleDTO] = Field(
        description="Its articles, in the order of the list."
    )
    missing: list[str] = Field(
        description="Its articles (`<BWB id>/<number>`) the data does not hold."
    )
    judgment_total: int = Field(
        description="The judgments that cite any of its articles, each once."
    )
    judgments: list[ConceptJudgmentDTO] = Field(
        description="The newest of them (5 at most), newest first."
    )
    document_total: int = Field(
        description="The papers joined to any of its articles, each once."
    )
    documents: list[ConceptDocumentDTO] = Field(
        description="The newest of them (2 at most), newest first."
    )

    @classmethod
    def of(cls, concept: Concept, overview: dict[str, Any]) -> ConceptResponse:
        """Build from the concept and its ``concept_overview``."""
        docs = {d["id"]: d for d in overview.get("articles") or []}
        counts = overview.get("judgment_counts") or {}
        refs = dict(zip(concept.article_ids, concept.articles, strict=True))
        explanation = (
            ConceptExplanationDTO(
                label=concept.explanation_label, url=concept.explanation_url
            )
            if concept.explanation_label and concept.explanation_url
            else None
        )
        return cls(
            key=concept.key,
            name=concept.name,
            explanation=explanation,
            articles=[
                ConceptArticleDTO.from_doc(docs[i], int(counts.get(i) or 0))
                for i in concept.article_ids
                if i in docs
            ],
            missing=[ref for i, ref in refs.items() if i not in docs],
            judgment_total=int(overview.get("judgment_total") or 0),
            judgments=[
                ConceptJudgmentDTO(
                    judgment=CitedByJudgment.from_doc(row["judgment"]),
                    article_ids=list(row.get("article_ids") or []),
                )
                for row in overview.get("judgments") or []
            ],
            document_total=int(overview.get("document_total") or 0),
            documents=[
                ConceptDocumentDTO.from_row(row)
                for row in overview.get("documents") or []
            ],
        )

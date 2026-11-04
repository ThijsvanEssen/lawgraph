"""The judgments that cite an article: the passages of ``/cited-by`` and their counts."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from lawgraph.api.schemas.citation_origin import CitationOriginFields
from lawgraph.api.schemas.common import (
    FacetCountDTO,
    JudgmentOutcomeFields,
    PathSource,
    QualifierFields,
    StrictModel,
    WithCite,
    WithPath,
    judgment_cite_dto,
    judgment_outcome_fields,
)
from lawgraph.core.judgment_metadata import subject_areas
from lawgraph.core.mentions import Mention


class CitedByJudgment(JudgmentOutcomeFields, WithCite, WithPath):
    """The judgment of a passage that cites an article, with how it ended."""

    path_source = PathSource("judgments")

    id: str
    key: str
    ecli: str | None
    court: str | None = Field(description="ECLI court code, `HR`, `RBAMS`.")
    tier: str | None = Field(
        description="The tier, the Type of the court in the Instanties value list: "
        "`hoge_raad`, `raad_van_state`, `parket`, `gerechtshof`, `rechtbank`, "
        "`andere_instantie`, … (`/api/stats/coverage` lists those present).",
    )
    court_kind: str | None = Field(
        default=None,
        description="The kind of court within the tier (`ambtenarengerecht`; a tier of "
        "one kind of court is its own kind).",
    )
    date: str | None = Field(description="Date of the judgment, YYYY-MM-DD.")
    display_name: str | None
    inbound_citation_count: int | None = Field(
        default=None,
        description="The judgments that cite it, or another publication of the same "
        "decision, each once (as in `/api/judgments`): a standard judgment has many.",
    )
    subject_areas: list[str] = Field(
        default_factory=list,
        description="The main areas of law of the judgment (`Strafrecht`, `Civiel recht`, "
        "`Bestuursrecht`), each once, as `subject_areas` of `/api/judgments/{ecli}`; "
        "empty when the source gives none.",
    )


def _passage_fields(mention: Mention | None) -> dict[str, Any]:
    """What ``ArticleCitedByItem`` says of a passage; all null without one."""
    if mention is None:
        return dict.fromkeys(
            (
                "paragraph_id",
                "paragraph_number",
                "qualifier",
                "start",
                "end",
                "text",
                "snippet",
                "confidence",
            )
        )
    return {
        "paragraph_id": mention.paragraph_id,
        "paragraph_number": mention.paragraph_number,
        "qualifier": mention.qualifier,
        "start": mention.start,
        "end": mention.end,
        "text": mention.raw_match,
        "snippet": mention.snippet,
        "confidence": mention.confidence,
        **mention.parts.to_dict(),
    }


class ArticleCitedByItem(QualifierFields, CitationOriginFields):
    """One passage of a judgment that cites the article. `leden`, `onderdelen` and
    `aanhef` say what the passage names of it. A judgment only its metadata links to the
    article has no passage: one row, with null for all that describes a passage."""

    judgment: CitedByJudgment
    paragraph_id: str | None = Field(
        description="The paragraph, as `paragraph_id` of `/api/judgments/{ecli}`; null "
        "for a judgment without a passage."
    )
    paragraph_number: str | None = Field(
        description="Its printed number (`5.3`), null when it has none."
    )
    qualifier: str | None = Field(
        description="The qualifier as the judgment wrote it, `derde lid`."
    )
    start: int | None = Field(
        description="Offset of the citation in the text of the paragraph."
    )
    end: int | None
    text: str | None = Field(description="The citation as written: `text[start:end]`.")
    snippet: str | None = Field(
        description="The text of the paragraph around the citation."
    )
    confidence: float | None

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> ArticleCitedByItem | None:
        """Build from a `{judgment, mention, origin}` row, without a mention one without a
        passage; None for a malformed mention."""
        mention = Mention.from_dict(row.get("mention"))
        if mention is None and row.get("mention") is not None:
            return None
        doc = row["judgment"]
        props = doc.get("props") or {}
        return cls(
            judgment=CitedByJudgment(
                id=doc["id"],
                key=doc["key"],
                ecli=props.get("ecli"),
                court=props.get("court_code"),
                tier=props.get("tier"),
                court_kind=props.get("court_kind"),
                date=props.get("date_eff"),
                display_name=props.get("display_name"),
                inbound_citation_count=props.get("inbound_citation_count"),
                subject_areas=subject_areas(props.get("subjects")),
                cite=judgment_cite_dto(props),
                **judgment_outcome_fields(props),
            ),
            origin=row.get("origin"),
            **_passage_fields(mention),
        )


class CitedByFacets(StrictModel):
    """The judgments that cite an article, counted whatever the page, each facet under the
    other filters."""

    year: list[FacetCountDTO] = Field(
        description="Per year of the judgment's date, oldest first, null (no date) "
        "first; without the `year` filter."
    )
    tier: list[FacetCountDTO] = Field(
        description="Per tier, most first; without the `tier` filter."
    )
    subject_area: list[FacetCountDTO] = Field(
        description="Per main area of law of the source (`Strafrecht`, `Civiel recht`, "
        "`Bestuursrecht`), most first; a judgment counts for each of its areas; without "
        "the `subject_area` filter."
    )


class ArticleCitedByResponse(StrictModel):
    """Response for GET /api/articles/{bwb_id}/{article_number}/cited-by."""

    article_id: str
    items: list[ArticleCitedByItem]
    total: int = Field(
        description="Every row that matches the filters, independent of `limit`."
    )
    judgment_total: int = Field(
        description="The judgments of those rows: a judgment that cites the article in "
        "three places is three rows and one judgment."
    )
    echr_judgment_total: int = Field(
        default=0,
        description="The ECHR judgments that cite the article, whatever the filters. "
        "HUDOC names the articles a judgment applies, not the passage, so they are no "
        "row of `items`; `GET /api/instruments/{identifier}/eu-links` lists them "
        "(`international`).",
    )
    facets: CitedByFacets

"""Document responses: lists and full text."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from lawgraph.core.documents import chamber_of, is_explanatory

Chamber = Literal["TK", "EK"]
ExplainedCollection = Literal["articles", "instruments"]


class DocumentOrigin(BaseModel):
    """Where a document comes from and what it is for; every document DTO carries it."""

    model_config = ConfigDict(extra="forbid")

    chamber: Chamber | None = Field(
        None,
        description=(
            "'TK' or 'EK'; null for a document that belongs to neither chamber, "
            "such as a Staatsblad or Staatscourant publication."
        ),
    )
    source: str | None = Field(
        None, description="Source, e.g. 'tk', 'eerstekamer', 'staatsblad'."
    )
    is_explanatory: bool = Field(
        False,
        description=(
            "An explanatory memorandum (memorie of nota van toelichting): a "
            "document of this kind explains the articles it introduces or changes."
        ),
    )


def origin_fields(
    labels: list[str] | None, source: str | None, kind: str | None
) -> dict[str, Any]:
    """The ``DocumentOrigin`` fields of a document with these labels, source and kind."""
    return {
        "chamber": chamber_of(labels),
        "source": source or None,
        "is_explanatory": is_explanatory(kind),
    }


class DocumentSummaryDTO(DocumentOrigin):
    """One row in the document index."""

    key: str
    title: str | None = None
    kind: str | None = None
    date: str | None = None
    external_id: str | None = None
    has_text: bool = False
    linked_articles: int = 0

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> DocumentSummaryDTO:
        from lawgraph.core.time import strip_time_component

        return cls(
            key=row["key"],
            title=row.get("title") or None,
            kind=row.get("kind") or None,
            date=strip_time_component(row.get("date")),
            external_id=row.get("external_id") or None,
            has_text=bool(row.get("has_text")),
            linked_articles=int(row.get("linked_articles") or 0),
            **origin_fields(row.get("labels"), row.get("source"), row.get("kind")),
        )


class DocumentListResponse(BaseModel):
    """A page of document summaries."""

    model_config = ConfigDict(extra="forbid")

    total: int = Field(
        ..., description="Matching documents, independent of ``limit`` and ``offset``."
    )
    items: list[DocumentSummaryDTO]


class ArticleRefDTO(BaseModel):
    """An article number a heading names."""

    model_config = ConfigDict(extra="forbid")

    number: str = Field(description="The number as printed: `3`, `1a`, `3:159n`, `II`.")
    of: str = Field(
        description=(
            "Whose article it is: `self` (of the bill the paper accompanies), "
            "`named_law` (of the law the section's `law` names) or `unknown` "
            "(of a law the heading implies and does not name)."
        )
    )


class SectionDTO(BaseModel):
    """One heading of a paper with the text under it: `text[char_start:char_end]`."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="`s-<ordinal>` in document order.")
    heading: str
    level: int = Field(
        description="1 for a section without parent, else its parent's + 1."
    )
    parent: str | None = Field(None, description="Id of the enclosing section.")
    kind: str = Field(
        description=(
            "`algemeen`, `artikelsgewijs`, `article`, `onderdeel`, `lid`, `chapter` or `other`."
        )
    )
    number: str | None = Field(
        None, description="The number as printed in the heading."
    )
    number_scheme: str | None = Field(
        None, description="`arabic`, `roman`, `book_article` or `letter`."
    )
    article_refs: list[ArticleRefDTO] = Field(
        default_factory=list, description="Every article number the heading names."
    )
    law: str | None = Field(None, description="Another law the heading names.")
    char_start: int
    char_end: int


class ExplainedTargetDTO(BaseModel):
    """What an explanatory document explains: an article, or a law as a whole.

    A version of an article resolves to the article itself; a law the document
    explains without naming articles is an instrument with ``article_number`` null.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., description="Arango _id of the article or instrument.")
    key: str
    collection: ExplainedCollection
    bwb_id: str | None = None
    article_number: str | None = None


class DocumentTextResponse(DocumentOrigin):
    """One document with its text.

    ``text`` is null until ``normalize tk-content`` has run for it: a paper
    from before December 1994 has no XML and never gets one. ``sections`` are
    the headings of the paper in document order, empty when there is no text or
    the structure of the paper could not be read; their offsets are into
    ``text``. ``dossier_numbers`` are the dossiers the document is PART_OF, in
    either chamber; ``explains`` are the articles and instruments it explains,
    without duplicates.
    """

    key: str
    document_id: str
    title: str | None = None
    kind: str | None = None
    date: str | None = None
    external_id: str | None = None
    tk_url: str | None = Field(None, description="The document on tweedekamer.nl.")
    text: str | None = None
    dossier_numbers: list[str] = Field(default_factory=list)
    explains: list[ExplainedTargetDTO] = Field(default_factory=list)
    sections: list[SectionDTO] = Field(default_factory=list)

    @classmethod
    def from_document(
        cls, doc: dict[str, Any], links: dict[str, Any] | None = None
    ) -> DocumentTextResponse:
        """From the stored document and what ``get_document_links`` found for it."""
        from lawgraph.config.constants import SOURCE_TK
        from lawgraph.config.settings import TK_DOCUMENT_RESOURCE_URL_TEMPLATE
        from lawgraph.core.time import strip_time_component

        props: dict[str, Any] = doc.get("props") or {}
        links = links or {}
        external_id: str | None = props.get("external_id")
        date = props.get("date") or (props.get("raw") or {}).get("Datum")
        text: str | None = props.get("text")
        return cls(
            key=doc["_key"],
            document_id=doc["_id"],
            title=props.get("title"),
            kind=props.get("kind"),
            date=strip_time_component(date),
            external_id=external_id,
            tk_url=(
                TK_DOCUMENT_RESOURCE_URL_TEMPLATE.format(external_id=external_id)
                if external_id and props.get("source") == SOURCE_TK
                else None
            ),
            text=text,
            sections=readable_sections(text, props.get("sections")),
            dossier_numbers=list(links.get("dossier_numbers") or []),
            explains=[ExplainedTargetDTO(**t) for t in links.get("explains") or []],
            **origin_fields(doc.get("labels"), props.get("source"), props.get("kind")),
        )


class PassageDTO(BaseModel):
    """The passage of a memorandum that explains an article."""

    model_config = ConfigDict(extra="forbid")

    section_id: str = Field(
        description="`id` of the section in `sections` of the document."
    )
    heading: str
    level: int | None = None
    char_start: int
    char_end: int
    text: str = Field(description="`text[char_start:char_end]` of the document.")
    confidence: float = Field(description="Uncalibrated: 0.7 to 0.9, see `match_type`.")
    match_type: str = Field(
        description=(
            "How the section names the article: `heading_target`, `body_named_law`, "
            "`own_number` or `inferred_law`."
        )
    )


class DocumentPassagesResponse(BaseModel):
    """The passages of one document that explain one article, in document order."""

    model_config = ConfigDict(extra="forbid")

    total: int
    items: list[PassageDTO]


def readable_sections(text: str | None, sections: Any) -> list[SectionDTO]:
    """The sections that lie in *text*: none without a text, none beyond its end."""
    if not text or not isinstance(sections, list):
        return []
    return [
        SectionDTO.model_validate(section)
        for section in sections
        if isinstance(section, dict) and section.get("char_end", 0) <= len(text)
    ]

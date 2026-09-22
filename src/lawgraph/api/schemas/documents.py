"""Document responses: lists and full text."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class DocumentSummaryDTO(BaseModel):
    """One row in the document index."""

    model_config = ConfigDict(extra="forbid")

    key: str
    title: str | None = None
    kind: str | None = None
    date: str | None = None
    external_id: str | None = None
    source: str | None = None
    has_text: bool = False
    linked_articles: int = 0


class DocumentListResponse(BaseModel):
    """A page of document summaries."""

    model_config = ConfigDict(extra="forbid")

    total: int
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


class DocumentTextResponse(BaseModel):
    """One document with its text.

    ``text`` is null until ``normalize tk-content`` has run for it: a paper
    from before December 1994 has no XML and never gets one. ``sections`` are
    the headings of the paper in document order, empty when there is no text or
    the structure of the paper could not be read; their offsets are into
    ``text``.
    """

    model_config = ConfigDict(extra="forbid")

    key: str
    document_id: str
    title: str | None = None
    kind: str | None = None
    date: str | None = None
    external_id: str | None = None
    tk_url: str | None = Field(None, description="The document on tweedekamer.nl.")
    text: str | None = None
    sections: list[SectionDTO] = Field(default_factory=list)

    @classmethod
    def from_document(cls, doc: dict[str, Any]) -> DocumentTextResponse:
        from lawgraph.config.constants import SOURCE_TK
        from lawgraph.config.settings import TK_DOCUMENT_RESOURCE_URL_TEMPLATE
        from lawgraph.core.time import strip_time_component

        props: dict[str, Any] = doc.get("props") or {}
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

"""Document responses: lists and full text."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from lawgraph.core.documents import chamber_of, is_explanatory
from lawgraph.core.models import NodeType
from lawgraph.core.tk_links import tk_url
from lawgraph.core.tk_records import submitters

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


def paper_number(chamber: str | None, props: dict[str, Any]) -> str | None:
    """Its number in the dossier as its chamber numbers it: the nr. of a Tweede Kamer paper
    (its ``sequence``), the letter of an Eerste Kamer one (its ``number``)."""
    if chamber == "EK":
        return props.get("number")
    sequence = props.get("sequence")
    return str(sequence) if chamber == "TK" and sequence else None


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


class SubmitterDTO(BaseModel):
    """Who submitted a motie or amendement."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="As the paper names them: `C.A.M. van der Plas`.")
    faction: str | None = Field(None, description="The faction they signed for.")
    member_key: str | None = Field(
        None, description="Their member (`/api/nodes/members/{key}`)."
    )
    role: Literal["indiener", "medeindiener"] = Field(
        description="`indiener` (the first signatory) or `medeindiener`."
    )


class DocumentTextResponse(DocumentOrigin):
    """One document with its text.

    ``text`` is null until ``normalize tk-content`` has run for it: a paper
    from before December 1994 has no XML and never gets one. ``sections`` are
    the headings of the paper in document order, empty when there is no text or
    the structure of the paper could not be read; their offsets are into
    ``text``. ``submitters`` are who submitted a motie or amendement, the indiener
    first (empty for any other paper). ``dossier_numbers`` are the dossiers the
    document is PART_OF, in either chamber; ``case_kinds`` the ``Zaak.Soort`` of the
    cases it belongs to (Tweede Kamer only); ``explains`` are the articles and
    instruments it explains, without duplicates.
    """

    key: str
    document_id: str
    title: str | None = None
    kind: str | None = None
    date: str | None = None
    external_id: str | None = None
    tk_url: str | None = Field(None, description="The document on tweedekamer.nl.")
    file_url: str | None = Field(
        None,
        description="The original file of a Tweede Kamer document (Word or PDF), from the "
        "Gegevensmagazijn.",
    )
    text: str | None = None
    submitters: list[SubmitterDTO] = Field(default_factory=list)
    dossier_numbers: list[str] = Field(default_factory=list)
    case_kinds: list[str] = Field(default_factory=list)
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
            tk_url=tk_url(NodeType.DOCUMENT.value, props),
            file_url=(
                TK_DOCUMENT_RESOURCE_URL_TEMPLATE.format(external_id=external_id)
                if external_id and props.get("source") == SOURCE_TK
                else None
            ),
            text=text,
            sections=readable_sections(text, props.get("sections")),
            submitters=[
                SubmitterDTO(**row)
                for row in submitters(props.get("kind"), props.get("actors") or [])
            ],
            dossier_numbers=list(links.get("dossier_numbers") or []),
            case_kinds=list(props.get("case_kinds") or []),
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
    confidence: float = Field(
        description="The share of such matches a hand check found right (0.3 to 0.95), "
        "by `match_type` and `changed`."
    )
    match_type: str = Field(
        description=(
            "How the section names the article: `heading_target`, `body_named_law`, "
            "`own_number` or `inferred_law`."
        )
    )
    changed: bool | None = Field(
        default=None,
        description="Whether the dossier changed the article, which corroborates the "
        "match; a heading naming an article the dossier left alone is often of another "
        "law. Null for a link made before this was recorded.",
    )
    explanation: str | None = Field(
        default=None,
        description="What the match rests on, in Dutch: the heading, and whether the "
        "dossier changed the article.",
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


class DocumentListItemDTO(BaseModel):
    """A paper of a chamber in the list: its metadata, no text."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    chamber: Literal["TK", "EK"] | None = None
    kind: str | None = Field(
        None, description="As the chamber writes it: ``Memorie van toelichting``."
    )
    dossier_number: str | None = Field(
        None,
        description="The dossier it is numbered in (its own; null for a paper that is no "
        "Kamerstuk): ``36791``.",
    )
    dossier_suffix: str | None = Field(
        None, description="The addition to that number: ``XV`` of ``37020 XV``."
    )
    dossier_numbers: list[str] = Field(
        default_factory=list, description="Every dossier it is part of, as labels."
    )
    number: str | None = Field(
        None,
        description="Its number in the dossier: of the Tweede Kamer the nr. (``5``), of "
        "the Eerste Kamer the letter (``C``); null for none.",
    )
    date: str | None = None
    title: str | None = None
    session_year: str | None = Field(
        None,
        description="The session year as the source writes it (``2025-2026``): with the "
        "chamber, dossier and number the citation, Kamerstukken I 2025/26, 36791, C.",
    )

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> DocumentListItemDTO:
        return cls(
            id=row["id"],
            key=row["key"],
            chamber=row.get("chamber"),
            kind=row.get("kind"),
            dossier_number=row.get("dossier_number"),
            dossier_suffix=row.get("dossier_suffix"),
            dossier_numbers=row.get("dossier_numbers") or [],
            number=paper_number(row.get("chamber"), row),
            date=row.get("date"),
            title=row.get("title"),
            session_year=row.get("session_year"),
        )


class DocumentFacetsDTO(BaseModel):
    """The papers under the filters, per kind (without the kind filter) and per chamber
    (without the chamber filter), the largest first."""

    model_config = ConfigDict(extra="forbid")

    kind: list[DocumentFacetCountDTO] = Field(default_factory=list)
    chamber: list[DocumentFacetCountDTO] = Field(default_factory=list)


class DocumentFacetCountDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str | None = None
    count: int


class DocumentListResponse(BaseModel):
    """A page of the papers of the chambers, newest first."""

    model_config = ConfigDict(extra="forbid")

    total: int | None = Field(
        None, description="Every match, whatever the page; null with ``facets=false``."
    )
    items: list[DocumentListItemDTO] = []
    facets: DocumentFacetsDTO | None = None

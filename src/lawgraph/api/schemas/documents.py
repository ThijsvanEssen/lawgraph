"""Document responses: lists and full text."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field

from lawgraph.api.params import MinistryKey
from lawgraph.api.schemas.common import (
    DossierNameDTO,
    FacetCountDTO,
    PathSource,
    StrictModel,
    WithPath,
    dossier_names_of,
)
from lawgraph.api.schemas.decisions import DecisionDTO
from lawgraph.config.constants import Chamber
from lawgraph.core.document_reading import footnote_id, section_at
from lawgraph.core.documents import (
    chamber_of,
    document_sender,
    is_explanatory,
    number_in_dossier,
)
from lawgraph.core.feed import SubmitterRole
from lawgraph.core.models import NodeType
from lawgraph.core.time import strip_time_component
from lawgraph.core.tk_links import document_file_url, tk_url
from lawgraph.core.tk_records.actors import SigningCapacity, submitters
from lawgraph.core.votes import DocumentOutcome

ExplainedCollection = Literal["articles", "instruments"]


class SenderDTO(StrictModel):
    """Who sent a Tweede Kamer paper: its first signatory, else the signature the source
    calls its sender (``Afzender``), as the source gives it."""

    name: str | None = Field(None, description="As the source writes it.")
    function: str | None = Field(
        None,
        description="The function they signed in: 'minister van Financiën', "
        "'Tweede Kamerlid'; null when the source gives none.",
    )
    faction: str | None = Field(None, description="Of a Kamerlid: the faction.")
    capacity: SigningCapacity | None = Field(
        None,
        description="'bewindspersoon' (a letter of the government), 'kamerlid' or "
        "'overig' (the griffier, the Raad van State, ...).",
    )
    member_key: str | None = Field(None, description="Their Member node, if named.")
    ministry: MinistryKey | None = Field(
        None, description="Of a bewindspersoon the ministry their function names."
    )


def sender_of(props: dict[str, Any]) -> SenderDTO | None:
    """The ``SenderDTO`` of a document with these props (its ``actors`` and ``date``)."""
    sender = document_sender(props.get("actors"), props.get("date"))
    return SenderDTO(**sender) if sender else None


class DocumentOrigin(StrictModel):
    """Where a document comes from and what it is for; every document DTO carries it."""

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


class ArticleRefDTO(StrictModel):
    """An article number a heading names."""

    number: str = Field(description="The number as printed: `3`, `1a`, `3:159n`, `II`.")
    of: str = Field(
        description=(
            "Whose article it is: `self` (of the bill the paper accompanies), "
            "`named_law` (of the law the section's `law` names) or `unknown` "
            "(of a law the heading implies and does not name)."
        )
    )


class SectionDTO(StrictModel):
    """One heading of a paper with the text under it: `text[char_start:char_end]`."""

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


class DocumentFootnoteDTO(StrictModel):
    """A footnote of a paper, which ``text`` does not hold."""

    id: str = Field(
        description="`fn-<n>`, its place among the footnotes (`fn-1` the first): what a "
        "citation in it names (`meta.place.footnote_id` of a `REFERS_TO` edge). Unique in "
        "the paper; `label` is not, a paper of before 2010 numbers its footnotes per page."
    )
    label: str | None = Field(None, description="Its number as printed: `3`.")
    text: str
    at: int | None = Field(
        None,
        description="Where its marker stands in `text`: `text[:at]` are the words before "
        "it. Null for a footnote whose marker is not in the text (one of the header) and "
        "for a paper read before markers were kept.",
    )
    section_id: str | None = Field(
        None, description="The innermost section that holds `at`."
    )


def document_footnotes(props: dict[str, Any]) -> list[DocumentFootnoteDTO]:
    """The footnotes of a paper (``props.footnotes``), in their order."""
    sections = props.get("sections") or []
    length = len(props.get("text") or "")
    found: list[DocumentFootnoteDTO] = []
    for index, note in enumerate(props.get("footnotes") or []):
        if not isinstance(note, dict) or not note.get("text"):
            continue
        at = note.get("at")
        at = at if isinstance(at, int) and 0 <= at <= length else None
        found.append(
            DocumentFootnoteDTO(
                id=footnote_id(index),
                label=note.get("number") or None,
                text=str(note["text"]),
                at=at,
                section_id=section_at(sections, at) if at is not None else None,
            )
        )
    return found


class ExplainedTargetDTO(StrictModel):
    """What an explanatory document explains: an article, or a law as a whole.

    A version of an article resolves to the article itself; a law the document
    explains without naming articles is an instrument with ``article_number`` null.
    """

    id: str = Field(
        ..., description="Node id (``collection/key``) of the article or instrument."
    )
    key: str
    collection: ExplainedCollection
    bwb_id: str | None = None
    article_number: str | None = None


class SubmitterDTO(WithPath):
    """Who submitted a motie or amendement."""

    path_source = PathSource("members", key_field="member_key")

    name: str = Field(description="As the paper names them: `C.A.M. van der Plas`.")
    faction: str | None = Field(None, description="The faction they signed for.")
    member_key: str | None = Field(
        None, description="Their member (`/api/nodes/members/{key}`)."
    )
    role: SubmitterRole = Field(
        description="`indiener` (the first signatory) or `medeindiener`."
    )


class PaperRefDTO(StrictModel):
    """Another paper, by its id and its number in its dossier."""

    id: str
    key: str
    sequence: int | None = None


REPLACES = (
    'The papers this amended amendment or motion replaces ("ter vervanging van nr. 8", '
    "``Zaak.VervangenVanuit``, ``REVISES`` with the rule ``vervanging``), by number; "
    "empty for most."
)
REPLACED_BY = (
    "The papers that replace this one (an amended amendment or motion with a new number); "
    "empty for most."
)


_DICTUM = (
    "Of a motion, what it asks or says, as it writes it: the lines from ``verzoekt``, "
    "``roept … op``, ``spreekt uit``, ``draagt … op`` or ``vraagt`` to ``en gaat over tot "
    "de orde van de dag``; null for any other paper and for a motion without text."
)


class PaperOutcomeFields(StrictModel):
    """How a motion or an amendment ended, and what it says in a line (``semantic
    tk-paper-outcomes``, ``core/votes.py``); every field null for any other paper."""

    dictum: str | None = Field(None, description=_DICTUM)
    explanation: str | None = Field(
        None,
        description="Of an amendment, what it is for: the first paragraph of its "
        "Toelichting, whole sentences up to 400 characters; null for any other paper and "
        "for an amendment without text.",
    )
    outcome: DocumentOutcome | None = Field(
        None,
        description="How the Kamer decided on it: ``aangenomen``, ``verworpen`` (by its "
        "vote; the latest vote when there were several), ``ingetrokken``, ``aangehouden``, "
        "``vervallen`` (a decision without a vote), else the status the page of a motion of "
        "the Eerste Kamer states; ``vervangen`` for a paper without one that a newer paper "
        "replaces (``replaced_by``); null while nothing was decided.",
    )
    decided_on: str | None = Field(
        None, description="The date of the decision that gave ``outcome``."
    )
    tally: dict[str, int] | None = Field(
        None,
        description='The seats per choice of that vote (``{"Voor": 150}``, members on a '
        "roll call), as ``/api/decisions/{key}`` gives them; null without votes (a "
        "hamerstuk, a motion held).",
    )
    decision: str | None = Field(
        None,
        description="The key of that decision (``/api/decisions/{key}``); null without one.",
    )


def outcome_fields(values: dict[str, Any]) -> dict[str, Any]:
    """The ``PaperOutcomeFields`` of a paper with these props (or the row of a list)."""
    return {name: values.get(name) for name in PaperOutcomeFields.model_fields}


class DocumentTextResponse(PaperOutcomeFields, DocumentOrigin):
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
    number: str | None = Field(
        None,
        description="Its number in its dossier as its chamber numbers it: the nr. of a "
        "Tweede Kamer paper (``12``), the letter of an Eerste Kamer one (``A``).",
    )
    sender: SenderDTO | None = Field(
        None,
        description="Who sent a Tweede Kamer paper (``SenderDTO``); null for an Eerste "
        "Kamer paper and a paper without a signature.",
    )
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
    footnotes: list[DocumentFootnoteDTO] = Field(
        default_factory=list,
        description="The footnotes, in their order, each with where its marker stands in "
        "`text`. A citation in one (a `REFERS_TO` edge whose `meta.place.part` is "
        "`footnote`) names it by `footnote_id`, its `start` and `end` offsets into its "
        "`text`.",
    )
    replaces: list[PaperRefDTO] = Field(default_factory=list, description=REPLACES)
    replaced_by: list[PaperRefDTO] = Field(
        default_factory=list, description=REPLACED_BY
    )
    decisions: list[DecisionDTO] = Field(
        default_factory=list,
        description="The votes taken on this document, oldest first, each with how every "
        "faction (or, on a roll-call, every member) voted: of a motion or an amendment the "
        "vote on it, of a bill the votes on the bill. A decision is about the case of an "
        "agenda item it names; the document it was taken on is the oldest of that case, "
        "as the timeline of a dossier shows it. Empty for any other paper.",
    )

    @classmethod
    def from_document(
        cls,
        doc: dict[str, Any],
        links: dict[str, Any] | None = None,
        decisions: list[dict[str, Any]] | None = None,
        names: dict[str, dict[str, Any]] | None = None,
        replacements: dict[str, list[dict[str, Any]]] | None = None,
    ) -> DocumentTextResponse:
        """From the stored document with the slugs of its members (``get_document``) and
        what ``get_document_links`` found for it; *replacements* its own of
        ``get_replacements``."""
        props: dict[str, Any] = doc.get("props") or {}
        links = links or {}
        slugs: dict[str, str] = doc.get("member_slugs") or {}
        external_id: str | None = props.get("external_id")
        text: str | None = props.get("text")
        origin = origin_fields(
            doc.get("labels"), props.get("source"), props.get("kind")
        )
        return cls(
            key=doc["_key"],
            document_id=doc["_id"],
            title=props.get("title"),
            kind=props.get("kind"),
            number=number_in_dossier(origin["chamber"], props),
            sender=sender_of(props),
            date=strip_time_component(props.get("date")),
            external_id=external_id,
            tk_url=tk_url(NodeType.DOCUMENT.value, props),
            file_url=document_file_url(props),
            text=text,
            sections=readable_sections(text, props.get("sections")),
            footnotes=document_footnotes(props),
            submitters=[
                SubmitterDTO(
                    **row,
                    path_props={"slug": slugs.get(row.get("member_key") or "")},
                )
                for row in submitters(props.get("kind"), props.get("actors") or [])
            ],
            dossier_numbers=list(links.get("dossier_numbers") or []),
            case_kinds=list(props.get("case_kinds") or []),
            explains=[ExplainedTargetDTO(**t) for t in links.get("explains") or []],
            replaces=[
                PaperRefDTO(**r) for r in (replacements or {}).get("replaces", [])
            ],
            replaced_by=[
                PaperRefDTO(**r) for r in (replacements or {}).get("replaced_by", [])
            ],
            decisions=[
                DecisionDTO.from_document(d, names or {}) for d in decisions or []
            ],
            **origin,
            **outcome_fields(props),
        )


class PassageDTO(StrictModel):
    """The passage of a memorandum that explains an article."""

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
            "`own_number`, `inferred_law`, `bill_part` (an onderdeel of the bill) or `amendment` "
            "(the Toelichting of an adopted amendment)."
        )
    )
    changed: bool | None = Field(
        default=None,
        description="Whether the dossier changed the article, or established it as an "
        "article of the law it made, which corroborates the match; a heading naming an "
        "article the dossier left alone is often of another law. Null for a link made "
        "before this was recorded.",
    )
    explanation: str | None = Field(
        default=None,
        description="What the match rests on, in Dutch: the heading, and whether the "
        "dossier changed the article or established it.",
    )


class DocumentPassagesResponse(StrictModel):
    """The passages of one document that explain one article, in document order."""

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


class DocumentListItemDTO(PaperOutcomeFields, WithPath):
    """A paper of a chamber in the list: its metadata, no text."""

    path_source = PathSource("documents")

    id: str
    key: str
    chamber: Chamber | None = None
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
    dossiers: list[DossierNameDTO] = Field(
        default_factory=list,
        description="The names of ``dossier_numbers`` (or of ``dossier_number`` without "
        "them), in their order: ``number``, ``short_title``, ``title`` as "
        "``/api/dossiers`` gives them.",
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
    sender: SenderDTO | None = Field(
        None,
        description="Who sent a Tweede Kamer paper (``SenderDTO``); null for an Eerste "
        "Kamer paper and a paper without a signature.",
    )

    @classmethod
    def from_row(
        cls, row: dict[str, Any], names: dict[str, dict[str, Any]]
    ) -> DocumentListItemDTO:
        """From a row of ``list_documents`` and the names of the dossiers
        (``load_dossier_names``)."""
        numbers = row.get("dossier_numbers") or [row.get("dossier_number")]
        return cls(
            id=row["id"],
            key=row["key"],
            chamber=row.get("chamber"),
            kind=row.get("kind"),
            dossier_number=row.get("dossier_number"),
            dossier_suffix=row.get("dossier_suffix"),
            dossier_numbers=row.get("dossier_numbers") or [],
            dossiers=dossier_names_of(numbers, names),
            number=number_in_dossier(row.get("chamber"), row),
            date=row.get("date"),
            title=row.get("title"),
            session_year=row.get("session_year"),
            sender=sender_of(row),
            **outcome_fields(row),
        )


class DocumentFacetsDTO(StrictModel):
    """The papers under the filters, per kind (without the kind filter) and per chamber
    (without the chamber filter), the largest first."""

    kind: list[FacetCountDTO] = Field(default_factory=list)
    chamber: list[FacetCountDTO] = Field(default_factory=list)


class DocumentListResponse(StrictModel):
    """A page of the papers of the chambers, newest first."""

    total: int | None = Field(
        None, description="Every match, whatever the page; null with ``facets=false``."
    )
    items: list[DocumentListItemDTO] = []
    facets: DocumentFacetsDTO | None = None

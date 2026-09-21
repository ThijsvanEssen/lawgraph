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

    ``text`` is null until the hydration pipeline has run for it — a scanned
    PDF without a text layer never gets one. ``dossier_numbers`` are the dossiers
    the document is PART_OF, in either chamber; ``explains`` are the articles and
    instruments it explains, without duplicates.
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
            text=props.get("text"),
            dossier_numbers=list(links.get("dossier_numbers") or []),
            explains=[ExplainedTargetDTO(**t) for t in links.get("explains") or []],
            **origin_fields(doc.get("labels"), props.get("source"), props.get("kind")),
        )

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


class DocumentTextResponse(BaseModel):
    """One document with its text.

    ``text`` is null until ``normalize tk-content`` has run for it: a paper
    from before December 1994 has no XML and never gets one.
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

    @classmethod
    def from_document(cls, doc: dict[str, Any]) -> DocumentTextResponse:
        from lawgraph.config.constants import SOURCE_TK
        from lawgraph.config.settings import TK_DOCUMENT_RESOURCE_URL_TEMPLATE
        from lawgraph.core.time import strip_time_component

        props: dict[str, Any] = doc.get("props") or {}
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
        )

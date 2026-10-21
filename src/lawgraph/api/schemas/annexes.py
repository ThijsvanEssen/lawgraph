"""Annex endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from lawgraph.api.schemas.articles import (
    ArticleHeadingDTO,
    ArticlePartDTO,
    ArticleReferenceDTO,
    headings_from_props,
    parts_from_props,
)
from lawgraph.api.schemas.common import ArticleRelationDTO, StrictModel
from lawgraph.api.schemas.tables import ArticleTableDTO, tables_from_props
from lawgraph.config.constants import SCOPE_TYPE_FIXED


class AnnexEntryDTO(StrictModel):
    """One entry (list item) inside an annex."""

    index: int | None = None
    name: str | None = Field(
        None, description="The item's own text with its marker (`a. artikel 49`)."
    )
    description: str | None = None
    heading: str | None = Field(
        None,
        description="The paragraph that introduces its list, without the colon: the law "
        "the item falls under (`Gemeentewet`). Null when the list has none.",
    )
    parent_index: int | None = Field(
        None,
        description="The `index` of the entry this one is nested in (`1.` under "
        "`a. Boek 1:`); null for an item of an outermost list.",
    )


class AnnexDTO(StrictModel):
    """An annex: its heading, its text as that of an article (paragraphs, lists, tables,
    headings) and its list as entries."""

    id: str
    key: str
    bwb_id: str | None = None
    label: str | None = Field(
        None, description="As article text cites it: `1`, `I`, `Ia`."
    )
    display_name: str | None = Field(
        None, description="As its heading prints it: `Bijlage 1`, `Lijst Ia`."
    )
    title: str | None = Field(
        None, description="The title of its heading; null where it prints none."
    )
    description: str | None = Field(
        None,
        description="Its paragraphs outside its lists, a line each and cut at 2,000 "
        "characters, a table flat; `text` has them whole.",
    )
    text: str | None = Field(
        None,
        description="Its text as that of an article: a paragraph a line, a list item on a "
        "line of its own, a table a row a line (its cells separated by a tab), the heading "
        "of a division on a line of its own. Without its articles, which are articles of "
        "their own (`bijlage 2 artikel 9`); null for an annex of articles only.",
    )
    parts: list[ArticlePartDTO] = Field(
        default_factory=list,
        description="Its onderdelen and the paragraphs outside them, as spans of `text`.",
    )
    tables: list[ArticleTableDTO] = Field(
        default_factory=list, description="The tables in `text`, as spans of it."
    )
    headings: list[ArticleHeadingDTO] = Field(
        default_factory=list,
        description="The headings in `text` (of a division, a table), as spans of it.",
    )
    entries: list[AnnexEntryDTO] = Field(default_factory=list)
    stub: bool = False

    @classmethod
    def from_document(cls, doc: dict[str, Any]) -> AnnexDTO:
        props = doc.get("props") or {}
        entries = [
            AnnexEntryDTO(
                index=e.get("index"),
                name=e.get("name"),
                description=e.get("description"),
                heading=e.get("heading"),
                parent_index=e.get("parent_index"),
            )
            for e in (props.get("entries") or [])
            if isinstance(e, dict)
        ]
        return cls(
            id=doc["id"],
            key=doc["key"],
            bwb_id=props.get("bwb_id"),
            label=props.get("label"),
            display_name=props.get("display_name"),
            title=props.get("title"),
            description=props.get("description"),
            text=props.get("text"),
            parts=parts_from_props(props),
            tables=tables_from_props(props),
            headings=headings_from_props(props),
            entries=entries,
            stub=bool(props.get("stub") or False),
        )


class AnnexReferencedByItem(StrictModel):
    """An article that references an annex, with scope metadata."""

    article: ArticleRelationDTO
    scope_type: str = SCOPE_TYPE_FIXED
    explanation: str | None = None


class AnnexDetailResponse(StrictModel):
    """Response for GET /api/annexes/{key}."""

    annex: AnnexDTO
    references: list[ArticleReferenceDTO] = Field(
        default_factory=list,
        description="The links of its `text` to a regulation, an article, an annex or an EU "
        "act, in text order, as those of an article.",
    )
    referenced_by: list[AnnexReferencedByItem] = Field(default_factory=list)

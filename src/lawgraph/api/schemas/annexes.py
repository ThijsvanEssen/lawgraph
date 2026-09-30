"""Annex endpoints."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from lawgraph.api.schemas.common import ArticleRelationDTO


class AnnexEntryDTO(BaseModel):
    """One entry (list item) inside an annex."""

    model_config = ConfigDict(extra="forbid")

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


class AnnexDTO(BaseModel):
    """Annex metadata plus structured entries."""

    model_config = ConfigDict(extra="forbid")

    id: str
    key: str
    bwb_id: str | None = None
    label: str | None = None
    display_name: str | None = None
    title: str | None = None
    description: str | None = None
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
            id=doc["_id"],
            key=doc["_key"],
            bwb_id=props.get("bwb_id"),
            label=props.get("label"),
            display_name=props.get("display_name"),
            title=props.get("title"),
            description=props.get("description"),
            entries=entries,
            stub=bool(props.get("stub") or False),
        )


class AnnexReferencedByItem(BaseModel):
    """An article that references an annex, with scope metadata."""

    model_config = ConfigDict(extra="forbid")

    article: ArticleRelationDTO
    scope_type: str = "fixed"
    explanation: str | None = None


class AnnexDetailResponse(BaseModel):
    """Response for GET /api/annexes/{key}."""

    model_config = ConfigDict(extra="forbid")

    annex: AnnexDTO
    referenced_by: list[AnnexReferencedByItem] = Field(default_factory=list)

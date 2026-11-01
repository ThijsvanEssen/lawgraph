"""The laws above an instrument: their text leaves a matter to it (``semantic bwb``)."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from lawgraph.api.schemas.common import (
    InstrumentSummaryDTO,
    StrictModel,
    regulation_kind,
)


class AboveArticleDTO(StrictModel):
    """An article of a law above that says so."""

    id: str
    key: str
    article_number: str | None
    display_name: str | None


class InstrumentAboveItem(StrictModel):
    """A law whose text leaves a matter to this one, with the articles that say so."""

    instrument: InstrumentSummaryDTO
    kind: str | None = Field(description="Its BWB type, lower case.")
    articles: list[AboveArticleDTO]

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> InstrumentAboveItem:
        """From a row of ``get_above``."""
        law = row["instrument"]
        return cls(
            instrument=InstrumentSummaryDTO.from_document(law),
            kind=regulation_kind(law.get("props") or {}),
            articles=[
                AboveArticleDTO(
                    id=a["id"],
                    key=a["key"],
                    article_number=a.get("article_number"),
                    display_name=a.get("display_name"),
                )
                for a in row.get("articles") or []
            ],
        )


class InstrumentAboveResponse(StrictModel):
    """Response for GET /api/instruments/{bwb_id}/above."""

    bwb_id: str = Field(..., description="The identifier as asked for.")
    total: int
    items: list[InstrumentAboveItem] = Field(
        default_factory=list, description="The laws in force, by title."
    )

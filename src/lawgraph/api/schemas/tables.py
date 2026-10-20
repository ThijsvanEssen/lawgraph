"""The tables in a text as the API serves them (``core.text_tables.TextTable``): of an
article, a paper and a paragraph of a judgment alike."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from lawgraph.api.schemas.common import StrictModel


class ArticleCellSpanDTO(StrictModel):
    """A cell of a table that spans more than one column or row."""

    row: int = Field(description="Its row, counted from 0.")
    cell: int = Field(description="Its place among the cells of that row, from 0.")
    cols: int = Field(description="How many columns it covers.")
    rows: int = Field(description="How many rows it covers.")


class ArticleTableDTO(StrictModel):
    """A table in a text (of an article, a paper, a paragraph of a judgment), as a span of
    it: a row a line, its cells separated by a tab (an empty cell an empty string)."""

    start: int = Field(description="Offset of its first row in the text.")
    end: int
    head_rows: int = Field(description="How many of its first rows are its header.")
    columns: int = Field(
        description="How many columns it has; a row next to a cell that spans rows, or "
        "whose last cells are empty, has fewer cells."
    )
    spans: list[ArticleCellSpanDTO] = Field(
        default_factory=list, description="Its cells that span columns or rows."
    )


def text_tables(text: Any, stored: Any) -> list[ArticleTableDTO]:
    """The tables stored with *text* (``props.tables``, ``core.text_tables.TextTable``);
    one that does not fit the text is left out rather than failing the response."""
    if not isinstance(text, str) or not isinstance(stored, list):
        return []
    return [
        ArticleTableDTO.model_validate(table)
        for table in stored
        if isinstance(table, dict)
        and isinstance(table.get("start"), int)
        and isinstance(table.get("end"), int)
        and 0 <= table["start"] < table["end"] <= len(text)
    ]


def tables_from_props(props: dict[str, Any]) -> list[ArticleTableDTO]:
    """The tables stored on an article, a version or a paper (``text_tables``)."""
    return text_tables(props.get("text"), props.get("tables"))

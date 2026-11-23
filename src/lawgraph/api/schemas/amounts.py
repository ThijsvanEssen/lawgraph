"""The numbers in the text of an article: ``/api/articles/{bwb_id}/{article_number}/amounts``."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pydantic import Field

from lawgraph.api.schemas.common import StrictModel
from lawgraph.core.amount_series import Version, series


class AmountStepDTO(StrictModel):
    """A number in one version of the article."""

    version_key: str = Field(description="The `key` of the version (`history`).")
    valid_from: str | None = Field(
        description="The day it holds from: of its redaction, else its version's start."
    )
    valid_until: str | None = Field(
        description="The day its version ends (exclusive); null while in force."
    )
    value: float | None = Field(description="The value; null for a date.")
    date: str | None = Field(
        description="A date as `yyyy-mm-dd`, a day of every year as `--mm-dd`."
    )
    selected: bool = Field(description="True for the step of the version read.")


class AmountDTO(StrictModel):
    """A number in the text of the version read, with its value in each version."""

    kind: str = Field(description="`bedrag`, `percentage`, `termijn` or `datum`.")
    unit: str = Field(
        description="`EUR`, `%`, `dag`, `werkdag`, `week`, `maand`, `jaar`, `uur` or "
        "`datum`."
    )
    text: str = Field(description="The number as the text prints it: `€ 3.115`.")
    part: str | None = Field(
        description="The id of the part that holds it (`lid-2-onder-a`, as the `anchor` "
        "of a block of `/text`); null in an article without parts."
    )
    start: int = Field(description="Offset into the text of the version.")
    end: int = Field(description="Offset into the text of the version.")
    source: str = Field(
        description="`text`: as the law prints it; `redaction`: in what the editors of the "
        "BWB add after it ('per 1 juli 2026: € 14,99'), the value in force from "
        "`valid_from`."
    )
    cell: list[int] | None = Field(
        description="In a table: its row and its cell in that row, from 0; else null."
    )
    history: list[AmountStepDTO] = Field(
        description="The same number in each version around the one read, oldest first, "
        "as long as its part holds as many numbers of its kind; the step of the version "
        "read is `selected`."
    )


class ArticleAmountsResponse(StrictModel):
    """Response for GET /api/articles/{bwb_id}/{article_number}/amounts."""

    bwb_id: str
    article_number: str
    version_key: str | None = Field(
        description="The version read: in force on `date`, else the current one; null "
        "when none holds."
    )
    valid_from: str | None = Field(description="The start of that version.")
    valid_until: str | None = Field(
        description="The end of that version (exclusive); null while in force."
    )
    amounts: list[AmountDTO] = Field(description="Its numbers in text order.")


def amount_dto(row: Mapping[str, Any], steps: list[dict[str, Any]]) -> AmountDTO:
    """A number with its series."""
    return AmountDTO(
        kind=row["kind"],
        unit=row["unit"],
        text=row["text"],
        part=row["part"],
        start=row["span_start"],
        end=row["span_end"],
        source=row["source"],
        cell=row["cell"],
        history=[AmountStepDTO(**s) for s in steps],
    )


def amounts_response(
    bwb_id: str, article_number: str, found: Sequence[Version], at: int | None
) -> ArticleAmountsResponse:
    """The numbers of the version at *at* of *found* (None: no version holds)."""
    if at is None:
        return ArticleAmountsResponse(
            bwb_id=bwb_id,
            article_number=article_number,
            version_key=None,
            valid_from=None,
            valid_until=None,
            amounts=[],
        )
    version = found[at]
    return ArticleAmountsResponse(
        bwb_id=bwb_id,
        article_number=article_number,
        version_key=version.key,
        valid_from=version.valid_from,
        valid_until=version.valid_until,
        amounts=[amount_dto(row, steps) for row, steps in series(found, at)],
    )

"""``validity`` of an instrument and of an article (``core.validity``, docs/api.md
"Validity")."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from lawgraph.api.schemas.common import PathSource, StrictModel, WithPath
from lawgraph.core.validity import Validity, ValidityState

VALIDITY = (
    "Whether it holds today, from the dates its source gives (docs/api.md "
    '"Validity"); null where the source says nothing of it (an EU act, a treaty the '
    "Verdragenbank does not say is in force)."
)


class SuccessorLawDTO(WithPath):
    """A law that takes the place of this one: an official source places articles of it
    there (``TRANSPOSED_TO``)."""

    path_source = PathSource("instruments")

    id: str
    key: str
    bwb_id: str | None = None
    celex: str | None = None
    official_id: str | None = None
    title: str | None = None
    citation_title: str | None = None
    articles: int = Field(
        description="How many of the articles (of the law; of an article: itself) pass to "
        "it."
    )

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> SuccessorLawDTO:
        """Build from a ``db.queries.validity.successor_laws`` row."""
        props = row.get("props") or {}
        return cls(
            id=row["id"],
            key=row["key"],
            bwb_id=props.get("bwb_id"),
            celex=props.get("celex"),
            official_id=props.get("official_id"),
            title=props.get("title"),
            citation_title=props.get("citation_title"),
            articles=int(row.get("articles") or 0),
        )


class ValidityDTO(StrictModel):
    """Whether a law or an article holds today."""

    state: ValidityState = Field(
        description="`in_force`, `expired` (no longer in force: repealed or lapsed) or "
        "`not_in_force_yet` (enacted, not in force)."
    )
    date: str | None = Field(
        None,
        description="Of `expired` the first day it no longer held (`Vervallen per`); of "
        "`not_in_force_yet` the day it comes into force (null when not known); of "
        "`in_force` the first day it will no longer hold, when the source says so already "
        "(null otherwise).",
    )
    as_of: str | None = Field(
        None,
        description="The day the data of its source stands on: the Dutch day its "
        "retrieves last all ended well (`completeness.source.as_of` of `/api/stats`). "
        "The day to cite its text as holding on; null when the source has no run yet.",
    )
    successors: list[SuccessorLawDTO] = Field(
        default_factory=list,
        description="The laws that take its place, as an official source gives them "
        "(`TRANSPOSED_TO`), the one most articles pass to first: of a law those of its "
        "articles; of an article those of its own `successors`, else, when it has "
        "expired, those of its law. Empty when no source says.",
    )

    @classmethod
    def build(
        cls,
        validity: Validity | None,
        as_of: str | None,
        successors: list[SuccessorLawDTO],
    ) -> ValidityDTO | None:
        """The DTO of *validity*; None for none."""
        if validity is None:
            return None
        return cls(
            state=validity.state,
            date=validity.date,
            as_of=as_of,
            successors=successors,
        )

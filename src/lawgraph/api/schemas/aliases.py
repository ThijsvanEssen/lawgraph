"""The abbreviations of the laws (GET /api/aliases)."""

from __future__ import annotations

from pydantic import Field

from lawgraph.api.schemas.common import StrictModel


class AliasDTO(StrictModel):
    """An abbreviation of one law: `Cbw` stands for `BWBR0049999`."""

    abbreviation: str = Field(
        ..., description="As its source spells it: `Cbw`, `BW 7`."
    )
    law_id: str = Field(..., description="The BWB id or CELEX number it stands for.")


class AliasesResponse(StrictModel):
    """Response for GET /api/aliases."""

    codes: list[AliasDTO] = Field(
        default_factory=list,
        description="Every abbreviation that stands for one law, in alphabetical order "
        "ignoring case: the short title and the other abbreviations of the BWB (its "
        "WTI), then those kept by hand where the source gives none (an EU act: `AVG`). "
        "One that several laws share is left out, as a law without one is.",
    )
    families: dict[str, dict[str, str]] = Field(
        default_factory=dict,
        description="Code -> book -> BWB id, of a code whose books are regulations of their "
        'own: `{"BW": {"7": "BWBR0005290"}}`. A citation names the book: `7:658 BW`.',
    )
    names: dict[str, list[str]] = Field(
        default_factory=dict,
        description="Code -> the names it goes by besides its abbreviation: "
        '`{"BW": ["Burgerlijk Wetboek"]}`.',
    )

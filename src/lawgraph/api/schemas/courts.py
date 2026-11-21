"""Court map responses: the arrondissement and ressort of every municipality in a year."""

from __future__ import annotations

from typing import Any

from pydantic import Field

from lawgraph.api.schemas.common import StrictModel
from lawgraph.core.court_districts import LAW_BWB_ID, Check


class CourtAreaDTO(StrictModel):
    """An arrondissement or ressort as the CBS names it, with the article of the Wet op de
    rechterlijke indeling that draws it."""

    code: str = Field(..., description="The code of the CBS: ``AR09``, ``RT12``.")
    name: str = Field(
        ...,
        description="As the CBS names it: ``Oost-Brabant``, ``Gerechtshof Arnhem-Leeuwarden``.",
    )
    article_number: str | None = Field(
        None,
        description="The number of the article of the law that draws it (4 to 13 for an "
        "arrondissement, 14 to 17 for a ressort); null when the text names it otherwise.",
    )


class CourtDistrictDTO(StrictModel):
    """A municipality with the courts of its first instance and appeal."""

    code: str = Field(..., description="The code of the municipality: ``GM0796``.")
    name: str
    province: str
    district: CourtAreaDTO = Field(..., description="The rechtbank of first instance.")
    circuit: CourtAreaDTO = Field(..., description="The gerechtshof of appeal.")
    law_district: str | None = Field(
        None,
        description="The arrondissement the text of the law puts it in; null when it puts "
        "it in none or in more than one, or the year is not checked.",
    )
    district_check: Check | None = Field(
        None,
        description="How the text of the law compares to the CBS for the arrondissement: "
        "`agrees`, `differs` or `not_in_text` (a gap, shown and never filled in); null "
        "when the year is not checked.",
    )
    circuit_check: Check | None = Field(
        None, description="The same for the ressort of its arrondissement."
    )

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> CourtDistrictDTO:
        return cls(
            code=row["municipality_code"],
            name=row["municipality"],
            province=row["province"],
            district=CourtAreaDTO(
                code=row["district_code"],
                name=row["district"],
                article_number=row["district_article"],
            ),
            circuit=CourtAreaDTO(
                code=row["circuit_code"],
                name=row["circuit"],
                article_number=row["circuit_article"],
            ),
            law_district=row["law_district"],
            district_check=row["district_check"],
            circuit_check=row["circuit_check"],
        )


class CourtDistrictsDTO(StrictModel):
    """The court map of one year, by arrondissement and municipality."""

    year: int
    years: list[int] = Field(..., description="Every year there is, newest first.")
    checked: bool = Field(
        ...,
        description="Whether this year is checked against the text of the law (only the "
        "year of the text the data holds, today's).",
    )
    law_bwb_id: str = Field(
        LAW_BWB_ID, description="The BWB id of the Wet op de rechterlijke indeling."
    )
    source: str = Field(
        "CBS, Gebieden in Nederland (CC BY 4.0)",
        description="Where the map comes from.",
    )
    total: int
    items: list[CourtDistrictDTO]

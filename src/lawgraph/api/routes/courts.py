"""Court endpoints.

GET /api/courts/districts  — the arrondissement and ressort of every municipality in a year
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.schemas.courts import CourtDistrictDTO, CourtDistrictsDTO
from lawgraph.db import GraphStore
from lawgraph.db.queries.court_districts import districts_of, years
from lawgraph.db.queries.not_found import NotFound

router = APIRouter()


@router.get(
    "/districts",
    response_model=CourtDistrictsDTO,
    summary="Court map",
    description=(
        "The arrondissement (rechtbank) and ressort (gerechtshof) of every municipality in "
        "`year` (default the newest), as the CBS gives them, with the article of the Wet "
        "op de rechterlijke indeling that draws each. The year of the text the data holds "
        "is `checked`: per municipality whether that text puts it where the CBS does "
        "(`district_check`, `circuit_check`). A municipality the text does not name is "
        "`not_in_text`: a gap, shown and never filled in. A year without a map is 404."
    ),
    tags=["courts"],
)
def get_districts(
    store: Annotated[GraphStore, Depends(get_store)],
    year: Annotated[
        int | None,
        Query(ge=2013, le=2100, description="The year of the map; default the newest."),
    ] = None,
) -> CourtDistrictsDTO:
    there = years(store)
    chosen = year if year is not None else (there[0] if there else None)
    if chosen is None or chosen not in there:
        raise NotFound("court map of year", str(year) if year else "newest")
    rows = districts_of(store, chosen)
    return CourtDistrictsDTO(
        year=chosen,
        years=there,
        checked=any(row["district_check"] for row in rows),
        total=len(rows),
        items=[CourtDistrictDTO.from_row(row) for row in rows],
    )

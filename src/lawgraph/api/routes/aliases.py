"""GET /api/aliases — the one table of abbreviations of the laws."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from lawgraph.api.dependencies import get_store
from lawgraph.api.schemas.aliases import AliasDTO, AliasesResponse
from lawgraph.core.code_families import CODE_FAMILIES, FAMILY_NAMES
from lawgraph.db import GraphStore
from lawgraph.db.queries.search.parser import load_code_aliases

router = APIRouter()


@router.get(
    "",
    response_model=AliasesResponse,
    summary="The abbreviations of the laws",
    description=(
        "The one table of abbreviations the search, the titles and the short addresses "
        "(`/bw/7/658`) read: every abbreviation that stands for one law, from the BWB "
        "(the WTI) and, where it gives none, kept by hand; and the codes whose books are "
        "regulations of their own (`BW`), with their books and names. Changes with the "
        "data version alone (its `ETag`)."
    ),
)
def get_aliases(store: Annotated[GraphStore, Depends(get_store)]) -> AliasesResponse:
    codes = sorted(
        load_code_aliases(store).items(), key=lambda item: (item[0].casefold(), item[0])
    )
    return AliasesResponse(
        codes=[
            AliasDTO(abbreviation=abbreviation, law_id=law_id.upper())
            for abbreviation, law_id in codes
        ],
        families=CODE_FAMILIES,
        names=FAMILY_NAMES,
    )

"""The laws above an instrument, under ``/api/instruments``: apart from ``routes.instruments``,
which is full (the simplicity budget)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from lawgraph.api.dependencies import get_store
from lawgraph.api.schemas.above import InstrumentAboveItem, InstrumentAboveResponse
from lawgraph.db import GraphStore
from lawgraph.db.queries.delegations import get_above
from lawgraph.db.queries.instrument_scope import resolve_instrument

router = APIRouter()


@router.get(
    "/{bwb_id}/above",
    response_model=InstrumentAboveResponse,
    summary="The laws whose text leaves a matter to this one",
    description=(
        "The laws in force, by title, with an article in force whose text leaves a matter "
        "to this one with a link to it (`geregeld in`, `vindt regeling in`, `in … "
        "voorzien`), and those articles. It names it: the source gives no basis (art. 5, "
        "42, 50 and 51 of the Statuut for the Grondwet). Empty for an unknown instrument. "
        "A basis in the preamble: `.../basis`."
    ),
)
def get_instrument_above_route(
    bwb_id: str, store: Annotated[GraphStore, Depends(get_store)]
) -> InstrumentAboveResponse:
    instrument = resolve_instrument(store, bwb_id)
    rows = get_above(store, instrument["id"]) if instrument else []
    items = [InstrumentAboveItem.from_row(row) for row in rows]
    return InstrumentAboveResponse(bwb_id=bwb_id, total=len(items), items=items)

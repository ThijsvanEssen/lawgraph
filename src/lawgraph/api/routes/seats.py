"""Office endpoints.

GET /api/seats/{seat}  — an office over its renames: its holders, gaps and what is its own
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from lawgraph.api.dependencies import get_store
from lawgraph.api.schemas.seats import SeatDTO
from lawgraph.db import GraphStore
from lawgraph.db.queries.not_found import require
from lawgraph.db.queries.seats import get_seat

router = APIRouter()


@router.get(
    "/{seat:path}",
    response_model=SeatDTO,
    summary="Office",
    description=(
        "One office (``seat`` of a post in ``GET /api/cabinets/{key}``: ``ienw/minister``, "
        "``jenv/staatssecretaris/rechtsbescherming``), under every name its ministry went "
        "by: any of its names gives the same answer. A merger of ministries is no rename "
        "(`merged_from`, `merged_into`). The holders with their periods, `gaps` without a "
        "holder, and per list what can be attributed to it: `commitments` and `dossiers` "
        "count the lists filtered on ``seat``, and what may be its own but fits nobody. "
        "Something is attributed by who did it and the day: the post of that kind they "
        "held; with two such posts that day the ministry decides, else it is attributed to "
        "neither. A seat without a ministry (``staatssecretaris/…``) has no other names. The "
        "viceminister-president, a seat beside a minister's own, has nothing attributed."
    ),
    tags=["government"],
)
def get_seat_detail(
    seat: str,
    store: Annotated[GraphStore, Depends(get_store)],
) -> SeatDTO:
    return SeatDTO.from_row(require(get_seat(store, seat), "Seat", seat))

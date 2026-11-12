"""Office endpoints.

GET /api/seats         — every office someone held, by ministry, cabinet or held now
GET /api/seats/{seat}  — an office over its renames: its holders, gaps and what is its own
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.params import MinistryKey
from lawgraph.api.schemas.seats import SeatDTO, SeatListDTO, SeatSummaryDTO
from lawgraph.core.time import dutch_today
from lawgraph.db import GraphStore
from lawgraph.db.queries.not_found import require
from lawgraph.db.queries.seats import get_seat, list_seats

router = APIRouter()


@router.get(
    "",
    response_model=SeatListDTO,
    summary="Offices",
    description=(
        "Every office someone held (the ``seat`` of a post), each once over the names of "
        "its ministry, by ``seat``: its latest name, post and ministry, its first and last "
        "day, how many held it and who holds it today (`current`). `ministry` keeps the "
        "offices held under that ministry or one of its names; `cabinet` those held in "
        "that cabinet (key); `current` those someone holds today. A seat nobody holds "
        "today has an empty `current`: a gap or a former office, not filled in."
    ),
    tags=["government"],
)
def get_seats(
    store: Annotated[GraphStore, Depends(get_store)],
    ministry: Annotated[MinistryKey | None, Query()] = None,
    cabinet: Annotated[
        str | None,
        Query(description="Only the offices held in this cabinet (key)."),
    ] = None,
    current: Annotated[
        bool, Query(description="Only the offices someone holds today.")
    ] = False,
) -> SeatListDTO:
    rows = [
        row
        for row in list_seats(store, dutch_today().isoformat())
        if (ministry is None or ministry.value in row["ministries"])
        and (cabinet is None or cabinet in row["cabinets"])
        and (not current or row["current"])
    ]
    return SeatListDTO(
        total=len(rows), items=[SeatSummaryDTO.from_row(row) for row in rows]
    )


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

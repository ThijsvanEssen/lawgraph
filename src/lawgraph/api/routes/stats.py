from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from lawgraph.api.dependencies import get_store
from lawgraph.api.queries import get_db_stats
from lawgraph.api.schemas.stats import EdgeStatsDTO, InstrumentStatsDTO, StatsResponse
from lawgraph.db import ArangoStore

router = APIRouter()


@router.get(
    "",
    response_model=StatsResponse,
    summary="Database statistics",
    description="Document counts per collection and edge counts per relation type.",
    tags=["stats"],
)
def get_stats(store: Annotated[ArangoStore, Depends(get_store)]) -> StatsResponse:
    data = get_db_stats(store)
    return StatsResponse(
        nodes=data["nodes"],
        edges=EdgeStatsDTO(**data["edges"]),
        by_source=data.get("by_source", {}),
        instruments=InstrumentStatsDTO(**data.get("instruments", {})),
    )

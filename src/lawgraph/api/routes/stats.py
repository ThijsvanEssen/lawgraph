from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from lawgraph.api.dependencies import get_store
from lawgraph.api.queries import get_db_stats
from lawgraph.api.schemas import EdgeStatsDTO, StatsResponse
from lawgraph.db import ArangoStore

router = APIRouter()


@router.get(
    "",
    response_model=StatsResponse,
    summary="Database statistieken",
    description="Geeft het aantal documenten per collectie en het aantal edges per relatietype.",
    tags=["stats"],
)
def get_stats(store: Annotated[ArangoStore, Depends(get_store)]) -> StatsResponse:
    data = get_db_stats(store)
    return StatsResponse(
        nodes=data["nodes"],
        edges=EdgeStatsDTO(**data["edges"]),
    )

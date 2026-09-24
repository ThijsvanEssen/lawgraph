from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from lawgraph.api.dependencies import get_store
from lawgraph.api.schemas.stats import (
    CoverageCourtDTO,
    CoverageTierDTO,
    EdgeStatsDTO,
    InstrumentStatsDTO,
    JudgmentCoverageResponse,
    StatsResponse,
)
from lawgraph.core.judgments import TIERS
from lawgraph.db import ArangoStore
from lawgraph.db.queries.stats import get_db_stats, get_judgment_coverage

router = APIRouter()


@router.get(
    "",
    response_model=StatsResponse,
    summary="Database statistics",
    description=(
        "Document counts per collection without stubs, the stubs per collection (nodes "
        "known only because something refers to them) and edge counts per relation type."
    ),
    tags=["stats"],
)
def get_stats(store: Annotated[ArangoStore, Depends(get_store)]) -> StatsResponse:
    data = get_db_stats(store)
    return StatsResponse(
        nodes=data["nodes"],
        stubs=data.get("stubs", {}),
        edges=EdgeStatsDTO(**data["edges"]),
        by_source=data.get("by_source", {}),
        instruments=InstrumentStatsDTO(**data.get("instruments", {})),
    )


def _span(rows: list[CoverageCourtDTO]) -> tuple[str | None, str | None]:
    firsts = [r.first_date for r in rows if r.first_date]
    lasts = [r.last_date for r in rows if r.last_date]
    return (min(firsts) if firsts else None, max(lasts) if lasts else None)


@router.get(
    "/coverage",
    response_model=JudgmentCoverageResponse,
    summary="Which judgments the graph holds",
    description=(
        "The judgments whose text is loaded, per court tier and per court, with the date "
        "of the oldest and the newest of each; and how many judgments are known only "
        "because a loaded one cites them (`stubs`). A count of judgments anywhere in the "
        "API (the judgments that cite an article, for one) is a count of this selection, "
        "not of the case law."
    ),
    tags=["stats"],
)
def get_coverage(
    store: Annotated[ArangoStore, Depends(get_store)],
) -> JudgmentCoverageResponse:
    data = get_judgment_coverage(store)
    courts = sorted(
        (CoverageCourtDTO(**row) for row in data["courts"]),
        key=lambda c: (-c.count, c.court_code or ""),
    )
    tiers = []
    for tier in sorted(
        {c.tier for c in courts},
        key=lambda t: TIERS.index(t) if t in TIERS else len(TIERS),
    ):
        of_tier = [c for c in courts if c.tier == tier]
        first, last = _span(of_tier)
        tiers.append(
            CoverageTierDTO(
                tier=tier,
                count=sum(c.count for c in of_tier),
                first_date=first,
                last_date=last,
            )
        )
    first, last = _span(courts)
    return JudgmentCoverageResponse(
        total=sum(c.count for c in courts),
        first_date=first,
        last_date=last,
        stubs=int(data["stubs"]),
        tiers=tiers,
        courts=courts,
    )

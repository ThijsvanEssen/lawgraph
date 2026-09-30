from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from lawgraph.api.dependencies import get_store
from lawgraph.api.schemas.stats import (
    CoverageCourtDTO,
    CoverageTierDTO,
    DataAsOfDTO,
    EdgeStatsDTO,
    InstrumentStatsDTO,
    JudgmentCoverageResponse,
    StatsResponse,
)
from lawgraph.core.courts import TIERS, court_of
from lawgraph.db import ArangoStore
from lawgraph.db.queries.stats import (
    cached_data_as_of,
    get_db_stats,
    get_judgment_coverage,
)

router = APIRouter()


@router.get(
    "",
    response_model=StatsResponse,
    summary="Database statistics",
    description=(
        "Document counts per collection without stubs, the stubs per collection (nodes "
        "known only because something refers to them), the replaced publications of a "
        "decision (`replaced`) and edge counts per relation type. `nodes.judgments` counts "
        "a decision once, as `/api/judgments` does."
    ),
    tags=["stats"],
)
def get_stats(store: Annotated[ArangoStore, Depends(get_store)]) -> StatsResponse:
    data = get_db_stats(store)
    return StatsResponse(
        nodes=data["nodes"],
        stubs=data.get("stubs", {}),
        replaced=data.get("replaced", {}),
        edges=EdgeStatsDTO(**data["edges"]),
        by_source=data.get("by_source", {}),
        instruments=InstrumentStatsDTO(**data.get("instruments", {})),
        data_as_of={
            source: DataAsOfDTO(**row)
            for source, row in cached_data_as_of(store).items()
        },
    )


def _span(rows: list[CoverageCourtDTO]) -> tuple[str | None, str | None]:
    firsts = [r.first_date for r in rows if r.first_date]
    lasts = [r.last_date for r in rows if r.last_date]
    return (min(firsts) if firsts else None, max(lasts) if lasts else None)


def _without_replaced(data: dict) -> list[dict]:
    """The coverage rows per court, less the publications another one replaces: the courts
    count a decision once, as the lists do. A court left without judgments is left out."""
    replaced = {
        (r["source"], r["tier"], r["court_code"]): r["count"]
        for r in data.get("replaced", [])
    }
    rows = []
    for row in data["courts"]:
        key = (row["source"], row["tier"], row["court_code"])
        if (count := row["count"] - replaced.get(key, 0)) > 0:
            rows.append({**row, "count": count})
    return rows


def _kind(row: dict) -> str | None:
    """The kind of court of a coverage row, from the court table (no read of a judgment)."""
    found = court_of(row.get("court_code"), row.get("court"))
    return found.court_kind if found else None


@router.get(
    "/coverage",
    response_model=JudgmentCoverageResponse,
    summary="Which judgments the graph holds",
    description=(
        "The judgments whose text is loaded, per court tier and per court, with the date "
        "of the oldest and the newest of each; and how many judgments are known only "
        "because a loaded one cites them (`stubs`). A decision published twice counts "
        "once, as in `/api/judgments`: `replaced` counts the publications another loaded "
        "one replaces. A count of judgments anywhere in the "
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
        (
            CoverageCourtDTO(**row, court_kind=_kind(row))
            for row in _without_replaced(data)
        ),
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
        replaced=sum(r["count"] for r in data.get("replaced", [])),
        tiers=tiers,
        courts=courts,
    )

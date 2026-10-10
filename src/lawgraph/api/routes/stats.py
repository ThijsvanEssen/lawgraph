from __future__ import annotations

from functools import partial
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
from lawgraph.config.constants import (
    CHAMBER_TK,
    COLLECTION_ACTIVITIES,
    COLLECTION_CABINETS,
    COLLECTION_COMMITMENTS,
    COLLECTION_COMMITTEES,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_EDGES,
    COLLECTION_FACTIONS,
    COLLECTION_INSTRUMENT_VERSIONS,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    COLLECTION_MEMBERS,
)
from lawgraph.core.courts import TIERS, court_of
from lawgraph.db import GraphStore
from lawgraph.db.queries.decisions import DecisionFilters, counted_total
from lawgraph.db.queries.stats import (
    cached_data_as_of,
    get_db_stats,
    get_judgment_coverage,
)
from lawgraph.db.version_cache import cached, stale_wait

router = APIRouter()


def stats_data(store: GraphStore) -> dict:
    """The counts of ``/api/stats``: the same for every visitor; the counts of each table
    kept until that table changes, so a poll of judgments counts the judgments again."""
    return get_db_stats(
        store,
        lambda table, compute: cached(
            store, ("stats", table), compute, tables=(table,)
        ),
    )


# Per list of the explorer, the tables its first page reads: its total is kept until one of
# them changes (``list_totals``).
LIST_TABLES: dict[str, tuple[str, ...]] = {
    "instruments": (
        COLLECTION_INSTRUMENTS,
        COLLECTION_INSTRUMENT_VERSIONS,
        COLLECTION_EDGES,
    ),
    "judgments": (COLLECTION_JUDGMENTS, COLLECTION_EDGES),
    "dossiers": (COLLECTION_DOSSIERS, COLLECTION_DOCUMENTS, COLLECTION_EDGES),
    "documents": (COLLECTION_DOCUMENTS, COLLECTION_EDGES),
    "members": (COLLECTION_MEMBERS,),
    "bewindspersonen": (COLLECTION_MEMBERS,),
    "factions": (COLLECTION_FACTIONS, COLLECTION_MEMBERS, COLLECTION_EDGES),
    "committees": (COLLECTION_COMMITTEES, COLLECTION_EDGES),
    "cabinets": (
        COLLECTION_CABINETS,
        COLLECTION_MEMBERS,
        COLLECTION_COMMITMENTS,
        COLLECTION_DOSSIERS,
        COLLECTION_EDGES,
    ),
    "commitments": (
        COLLECTION_COMMITMENTS,
        COLLECTION_ACTIVITIES,
        COLLECTION_DOSSIERS,
        COLLECTION_MEMBERS,
        COLLECTION_EDGES,
    ),
}


def _list_total(store: GraphStore, name: str) -> int | None:
    """The total of the list *name* as its route answers it without a filter (its first
    page): the route itself is asked, so the number is the list's own."""
    # the routes, each asked as a request without parameters would ask it (without the
    # facets where the route can leave them out and still count the total)
    from lawgraph.api.routes import (
        committees,
        documents,
        dossiers,
        government,
        instruments,
        judgments,
    )
    from lawgraph.db.queries.committees import count_members

    if name == "instruments":
        return instruments.list_instruments(store=store, limit=1, facets=False).total
    if name == "judgments":
        return judgments.list_judgments(store=store, limit=1, facets=False).total
    if name == "dossiers":
        return dossiers._list(store, dossiers._ListParams(limit=1, facets=False)).total
    if name == "documents":
        return documents.list_chamber_documents(store=store, limit=1).total
    if name == "members":
        return count_members(store)
    if name == "bewindspersonen":
        return count_members(store, government=True)
    if name == "factions":
        return len(committees.list_factions(store=store))
    if name == "committees":
        return len(committees.list_committees(store=store))
    if name == "cabinets":
        return len(government.list_cabinets(store=store))
    if name == "commitments":
        return government.list_commitments(store=store, limit=1, facets=False).total
    raise KeyError(name)


def list_totals(store: GraphStore) -> dict[str, int | None]:
    """Per list of the explorer, the ``total`` it gives without a filter, each kept until
    its tables change; ``decisions`` as the list opens (the Tweede Kamer), from its kept
    count without waiting for it: null until it is counted (the warm-up counts it)."""
    totals: dict[str, int | None] = {
        name: cached(
            store,
            ("stats list", name),
            partial(_list_total, store, name),
            tables=tables,
        )
        for name, tables in LIST_TABLES.items()
    }
    totals["decisions"] = counted_total(store, DecisionFilters(chamber=CHAMBER_TK))
    return totals


def coverage_data(store: GraphStore) -> dict:
    """The counts of ``/api/stats/coverage``: kept until the judgments change. After a poll
    of judgments a request takes the counts of before at once while the new ones compute
    (a poll moves them by a handful; it waited ``STALE_WAIT``, 2.2 s on 10 Oct); the
    warm-up waits for them."""
    with stale_wait(0.0):
        return cached(
            store,
            ("coverage",),
            lambda: get_judgment_coverage(store),
            tables=(COLLECTION_JUDGMENTS,),
        )


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
def get_stats(store: Annotated[GraphStore, Depends(get_store)]) -> StatsResponse:
    data = stats_data(store)
    return StatsResponse(
        nodes=data["nodes"],
        stubs=data.get("stubs", {}),
        replaced=data.get("replaced", {}),
        edges=EdgeStatsDTO(**data["edges"]),
        by_source=data.get("by_source", {}),
        instruments=InstrumentStatsDTO(**data.get("instruments", {})),
        lists=list_totals(store),
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
    store: Annotated[GraphStore, Depends(get_store)],
) -> JudgmentCoverageResponse:
    data = coverage_data(store)
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

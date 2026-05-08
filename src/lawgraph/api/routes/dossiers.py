"""API routes for parliamentary dossiers.

GET /api/dossiers/{kamerstuknummer}           — dossier detail with summary counts
GET /api/dossiers/{kamerstuknummer}/timeline  — ordered timeline entries
GET /api/dossiers/{kamerstuknummer}/mutations — pending-mutation subgraph
GET /api/dossiers/open                        — all open dossiers (with filters)
GET /api/dossiers/recent                      — recently active dossiers
GET /api/partijen/kleuren                     — party color map for the frontend
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.queries import (
    get_dossier_by_nummer,
    get_dossier_mutations,
    get_dossier_timeline,
    get_open_dossiers,
    get_recent_dossiers,
)
from lawgraph.api.schemas import (
    PARTY_COLORS,
    DossierDetailResponse,
    DossierMutationEdge,
    DossierMutationNode,
    DossierMutationsResponse,
    DossierSummaryDTO,
    DossierTimelineResponse,
    PartyColorsResponse,
    TimelineEntryDTO,
)
from lawgraph.config.settings import COLLECTION_EDGES, RELATION_DEEL_VAN_DOSSIER
from lawgraph.db import ArangoStore

router = APIRouter()


# ── Helper ─────────────────────────────────────────────────────────────────────


def _dossier_or_404(store: ArangoStore, kamerstuknummer: str) -> dict:
    dossier = get_dossier_by_nummer(store, kamerstuknummer)
    if dossier is None:
        raise HTTPException(
            status_code=404, detail=f"Dossier {kamerstuknummer} niet gevonden."
        )
    return dossier


def _count_members(store: ArangoStore, dossier_id: str, collection: str) -> int:
    aql = f"""
    RETURN LENGTH(
        FOR e IN {COLLECTION_EDGES}
            FILTER e._to == @dossier_id OR e._from == @dossier_id
            FILTER e.relation == '{RELATION_DEEL_VAN_DOSSIER}'
            LET node_id = (e._to == @dossier_id ? e._from : e._to)
            FILTER SPLIT(node_id, '/')[0] == @collection
            RETURN 1
    )
    """
    rows = list(store.query(aql, {"dossier_id": dossier_id, "collection": collection}))
    return rows[0] if rows else 0


# ── Endpoints ──────────────────────────────────────────────────────────────────


@router.get(
    "/open",
    response_model=list[DossierSummaryDTO],
    summary="Alle open kamerstukdossiers",
    description=(
        "Geeft alle dossiers terug die nog niet zijn afgehandeld. "
        "Ondersteunt filters op commissie-slug, onderwerp-tekst en parlementaire fase."
    ),
    tags=["dossiers"],
)
def list_open_dossiers(
    store: Annotated[ArangoStore, Depends(get_store)],
    commissie: Annotated[
        str | None, Query(description="Filter op commissie-slug.")
    ] = None,
    onderwerp: Annotated[
        str | None, Query(description="Vrije-tekst filter op dossier-titel.")
    ] = None,
    fase: Annotated[
        str | None, Query(description="Filter op huidige_fase (bijv. 'wetsvoorstel').")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> list[DossierSummaryDTO]:
    docs = get_open_dossiers(
        store,
        commissie_slug=commissie,
        onderwerp=onderwerp,
        fase=fase,
        limit=limit,
    )
    return [DossierSummaryDTO.from_document(d) for d in docs]


@router.get(
    "/recent",
    response_model=list[DossierSummaryDTO],
    summary="Recent actieve kamerstukdossiers",
    description="Dossiers die activiteiten hadden in de opgegeven periode (standaard 30 dagen).",
    tags=["dossiers"],
)
def list_recent_dossiers(
    store: Annotated[ArangoStore, Depends(get_store)],
    days: Annotated[
        int, Query(ge=1, le=365, description="Terugkijkperiode in dagen.")
    ] = 30,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> list[DossierSummaryDTO]:
    docs = get_recent_dossiers(store, days=days, limit=limit)
    return [DossierSummaryDTO.from_document(d) for d in docs]


@router.get(
    "/{kamerstuknummer}",
    response_model=DossierDetailResponse,
    summary="Dossier detail",
    description=(
        "Volledige dossierweergave: koptekst, fase, gerelateerde dossiers en "
        "samenvattende tellingen van documenten, activiteiten, stemmingen en toezeggingen."
    ),
    tags=["dossiers"],
)
def get_dossier_detail(
    kamerstuknummer: str,
    store: Annotated[ArangoStore, Depends(get_store)],
) -> DossierDetailResponse:
    dossier = _dossier_or_404(store, kamerstuknummer)
    dossier_id = dossier["_id"]
    return DossierDetailResponse.from_document(
        dossier,
        document_count=_count_members(store, dossier_id, "publications"),
        activiteit_count=_count_members(store, dossier_id, "activiteiten"),
        stemming_count=_count_members(store, dossier_id, "stemmingen"),
        toezegging_count=_count_members(store, dossier_id, "toezeggingen"),
    )


@router.get(
    "/{kamerstuknummer}/timeline",
    response_model=DossierTimelineResponse,
    summary="Dossier tijdlijn",
    description=(
        "Chronologische lijst van tijdlijn-items (documenten, activiteiten, stemmingen, "
        "toezeggingen). Standaard nieuwste-eerst; gebruik `?order=asc` voor chronologisch. "
        "Filter op `?soort=motie,amendement` (komma-gescheiden)."
    ),
    tags=["dossiers"],
)
def get_timeline(
    kamerstuknummer: str,
    store: Annotated[ArangoStore, Depends(get_store)],
    order: Annotated[
        str, Query(description="Sorteervolgorde: 'desc' (nieuwste eerst) of 'asc'.")
    ] = "desc",
    soort: Annotated[
        str | None, Query(description="Komma-gescheiden lijst van documenttypes.")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> DossierTimelineResponse:
    dossier = _dossier_or_404(store, kamerstuknummer)
    dossier_id = dossier["_id"]

    soort_filter = [s.strip() for s in soort.split(",")] if soort else None
    order_val = "asc" if order.lower() == "asc" else "desc"

    rows = get_dossier_timeline(
        store,
        dossier_id,
        order=order_val,
        soort_filter=soort_filter,
        limit=limit,
    )
    entries = [
        TimelineEntryDTO(
            datum=row.get("datum"),
            soort=row.get("soort") or "",
            titel=row.get("titel"),
            node_id=row.get("node_id") or "",
            node_type=row.get("node_type") or "",
            body=row.get("body") or {},
        )
        for row in rows
    ]
    return DossierTimelineResponse(
        kamerstuknummer=kamerstuknummer,
        total=len(entries),
        order=order_val,
        entries=entries,
    )


@router.get(
    "/{kamerstuknummer}/mutations",
    response_model=DossierMutationsResponse,
    summary="Dossier mutatiegraph",
    description=(
        "Geeft de subgraph van dit dossier terug: knooppunten en edges met "
        "status='voorgesteld'. Dezelfde shape als het bestaande graph-endpoint "
        "zodat de frontend dit direct kan renderen."
    ),
    tags=["dossiers"],
)
def get_mutations(
    kamerstuknummer: str,
    store: Annotated[ArangoStore, Depends(get_store)],
) -> DossierMutationsResponse:
    dossier = _dossier_or_404(store, kamerstuknummer)
    raw = get_dossier_mutations(store, dossier["_id"])
    return DossierMutationsResponse(
        kamerstuknummer=kamerstuknummer,
        nodes=[DossierMutationNode.from_document(n) for n in raw.get("nodes", [])],
        edges=[
            DossierMutationEdge(
                from_id=e.get("from_id"),
                to_id=e.get("to_id"),
                relation=e.get("relation"),
                status=e.get("status"),
                meta=e.get("meta"),
            )
            for e in raw.get("edges", [])
        ],
    )


# ── Party colors ───────────────────────────────────────────────────────────────

party_router = APIRouter()


@party_router.get(
    "/kleuren",
    response_model=PartyColorsResponse,
    summary="Partijkleuren",
    description=(
        "Vaste kleurenmap (partij-afkorting → hex-kleur) voor het renderen van "
        "stemming-chips in de frontend. Gebaseerd op officiele partijhuisstijlen."
    ),
    tags=["partijen"],
)
def get_party_colors() -> PartyColorsResponse:
    return PartyColorsResponse(colors=PARTY_COLORS)

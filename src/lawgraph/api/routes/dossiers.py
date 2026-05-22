"""API routes for parliamentary dossiers.

GET /api/dossiers/{kamerstuknummer}           — dossier detail with summary counts
GET /api/dossiers/{kamerstuknummer}/timeline  — ordered timeline entries
GET /api/dossiers/{kamerstuknummer}/mutations — pending-mutation subgraph
GET /api/dossiers/open                        — all open dossiers (with filters)
GET /api/dossiers/recent                      — recently active dossiers
GET /api/partijen/kleuren                     — party color map for the frontend
"""

from __future__ import annotations

from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.queries import (
    count_dossier_members,
    enrich_dossier_docs,
    get_documents_for_dossiers,
    get_dossier_by_nummer,
    get_dossier_documents,
    get_dossier_mutations,
    get_dossier_timeline,
    get_kamerstuknummer_to_id_map,
    get_open_dossiers,
    get_recent_dossiers,
)
from lawgraph.api.schemas import (
    PARTY_COLORS,
    DossierDetailResponse,
    DossierDocumentDTO,
    DossierDocumentsBulkResponse,
    DossierDocumentsResponse,
    DossierListResponse,
    DossierMutationEdge,
    DossierMutationNode,
    DossierMutationsResponse,
    DossierSummaryDTO,
    DossierTimelineResponse,
    PartyColorsResponse,
    TimelineEntryDTO,
)
from lawgraph.db import ArangoStore

router = APIRouter()

_DOSSIER_NUMMER_PATTERN = r"^\d+(-[A-Za-z]+)?$"


# ── Helper ─────────────────────────────────────────────────────────────────────


def _dossier_or_404(store: ArangoStore, kamerstuknummer: str) -> dict[str, Any]:
    dossier = get_dossier_by_nummer(store, kamerstuknummer)
    if dossier is None:
        raise HTTPException(
            status_code=404, detail=f"Dossier {kamerstuknummer} not found."
        )
    return dossier


# ── Endpoints ──────────────────────────────────────────────────────────────────


@router.get(
    "/open",
    response_model=DossierListResponse,
    summary="Alle open kamerstukdossiers",
    description=(
        "Geeft alle dossiers terug die nog niet zijn afgehandeld. "
        "``total`` is het absolute aantal (onafhankelijk van ``limit``). "
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
        str | None,
        Query(
            description=(
                "Filter op huidige_fase: de meest recente herkende stage van het "
                "dossier (bijv. 'wetsvoorstel', 'mvt', 'amendementen'). Voor "
                "filters op aanwezigheid van een stage, gebruik `has_stage`."
            )
        ),
    ] = None,
    has_stage: Annotated[
        str | None,
        Query(
            description=(
                "Komma-gescheiden lijst van stages; geeft alleen dossiers terug "
                "die *alle* genoemde stages bevatten (bijv. `mvt,advies_rvs`)."
            )
        ),
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DossierListResponse:
    has_stage_list = (
        [s.strip() for s in has_stage.split(",") if s.strip()] if has_stage else None
    )
    raw = get_open_dossiers(
        store,
        commissie_slug=commissie,
        onderwerp=onderwerp,
        fase=fase,
        has_stage=has_stage_list,
        limit=limit,
        offset=offset,
    )
    docs = raw.get("items") or []
    enrich_dossier_docs(store, docs)
    return DossierListResponse(
        total=int(raw.get("total") or 0),
        items=[DossierSummaryDTO.from_document(d) for d in docs],
    )


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
    enrich_dossier_docs(store, docs)
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
    kamerstuknummer: Annotated[
        str,
        Path(
            description="Parliamentary dossier number, e.g. 29684 or 29684-I",
            pattern=_DOSSIER_NUMMER_PATTERN,
        ),
    ],
    store: Annotated[ArangoStore, Depends(get_store)],
) -> DossierDetailResponse:
    dossier = _dossier_or_404(store, kamerstuknummer)
    enrich_dossier_docs(store, [dossier])
    dossier_id = dossier["_id"]
    counts = count_dossier_members(store, dossier_id)
    return DossierDetailResponse.from_document(
        dossier,
        document_count=counts.get("publications", 0),
        activiteit_count=counts.get("activiteiten", 0),
        stemming_count=counts.get("stemmingen", 0),
        toezegging_count=counts.get("toezeggingen", 0),
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
    kamerstuknummer: Annotated[
        str,
        Path(
            description="Parliamentary dossier number, e.g. 29684 or 29684-I",
            pattern=_DOSSIER_NUMMER_PATTERN,
        ),
    ],
    store: Annotated[ArangoStore, Depends(get_store)],
    order: Annotated[
        Literal["asc", "desc"],
        Query(description="Sorteervolgorde: 'desc' (nieuwste eerst) of 'asc'."),
    ] = "desc",
    soort: Annotated[
        str | None, Query(description="Komma-gescheiden lijst van documenttypes.")
    ] = None,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> DossierTimelineResponse:
    dossier = _dossier_or_404(store, kamerstuknummer)
    dossier_id = dossier["_id"]

    soort_filter = [s.strip() for s in soort.split(",")] if soort else None

    rows = get_dossier_timeline(
        store,
        dossier_id,
        order=order,
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
            tk_url=row.get("tk_url"),
            body=row.get("body") or {},
        )
        for row in rows
    ]
    return DossierTimelineResponse(
        kamerstuknummer=kamerstuknummer,
        total=len(entries),
        order=order,
        entries=entries,
    )


@router.get(
    "/documents/bulk",
    response_model=DossierDocumentsBulkResponse,
    summary="Documenten voor meerdere dossiers in één call",
    description=(
        "Bulk-variant van /api/dossiers/{kamerstuknummer}/documents: "
        "geeft de top-N publicaties per dossier voor een lijst van "
        "kamerstuknummers. Vervangt N parallelle calls tijdens de "
        "Lagen-load. ``items`` is een map ``{kamerstuknummer: [docs]}``."
    ),
    tags=["dossiers"],
)
def get_documents_for_dossiers_route(
    store: Annotated[ArangoStore, Depends(get_store)],
    nummers: Annotated[
        str,
        Query(
            description="Comma-separated kamerstuknummers, e.g. '29684,29515-Z'.",
            min_length=1,
        ),
    ],
    per_dossier_limit: Annotated[int, Query(ge=1, le=50)] = 8,
) -> DossierDocumentsBulkResponse:
    nummer_list = [n.strip() for n in nummers.split(",") if n.strip()]
    if not nummer_list:
        return DossierDocumentsBulkResponse(items={})
    nummer_to_id = get_kamerstuknummer_to_id_map(store, nummer_list)
    if not nummer_to_id:
        return DossierDocumentsBulkResponse(items={})
    by_id = get_documents_for_dossiers(
        store,
        list(nummer_to_id.values()),
        per_dossier_limit=per_dossier_limit,
    )
    items = {
        nummer: [DossierDocumentDTO(**d) for d in by_id.get(did, [])]
        for nummer, did in nummer_to_id.items()
    }
    return DossierDocumentsBulkResponse(items=items)


@router.get(
    "/{kamerstuknummer}/documents",
    response_model=DossierDocumentsResponse,
    summary="Dossier documenten",
    description=(
        "Geeft de Kamerstuk-documenten (publicaties) die aan dit dossier zijn gekoppeld "
        "via DEEL_VAN_DOSSIER-edges, gepagineerd op datum aflopend. ``total`` is "
        "het absolute aantal documenten (onafhankelijk van ``limit``)."
    ),
    tags=["dossiers"],
)
def get_dossier_documents_route(
    kamerstuknummer: Annotated[
        str,
        Path(
            description="Parliamentary dossier number, e.g. 29684 or 29684-I",
            pattern=_DOSSIER_NUMMER_PATTERN,
        ),
    ],
    store: Annotated[ArangoStore, Depends(get_store)],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DossierDocumentsResponse:
    dossier = _dossier_or_404(store, kamerstuknummer)
    raw = get_dossier_documents(store, dossier["_id"], limit=limit, offset=offset)
    return DossierDocumentsResponse(
        total=int(raw.get("total") or 0),
        items=[DossierDocumentDTO(**d) for d in raw.get("items") or []],
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
    kamerstuknummer: Annotated[
        str,
        Path(
            description="Parliamentary dossier number, e.g. 29684 or 29684-I",
            pattern=_DOSSIER_NUMMER_PATTERN,
        ),
    ],
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
                kind=e.get("kind", "mutation"),
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

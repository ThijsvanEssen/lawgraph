"""Dossier endpoints.

GET /api/dossiers                      — every dossier, with filters, order and facets
GET /api/dossiers/{number}             — one dossier with its counts
GET /api/dossiers/{number}/documents   — its documents
GET /api/dossiers/{number}/timeline    — everything that happened, in order
GET /api/dossiers/{number}/mutations   — its pending-change subgraph
GET /api/dossiers/{number}/changed-articles — the articles it changes, per law
GET /api/parties/colors                — party colours for the frontend
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Path, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.params import MinistryKey, parse_choices
from lawgraph.api.schemas.dossier_changes import (
    DossierChange,
    DossierChangedArticlesResponse,
    DossierChangedLaw,
)
from lawgraph.api.schemas.dossiers import (
    DOSSIER_NUMBER_PATTERN,
    DossierDetailResponse,
    DossierDocumentDTO,
    DossierDocumentsResponse,
    DossierFacetsDTO,
    DossierListResponse,
    DossierMutationEdge,
    DossierMutationNode,
    DossierMutationsResponse,
    DossierOutcome,
    DossierSummaryDTO,
    DossierTimelineResponse,
    timeline_entry,
)
from lawgraph.core.dossier_stages import CARRYING_KINDS, PHASES
from lawgraph.core.law_names import laws_in_title
from lawgraph.db import GraphStore
from lawgraph.db.queries.dossier_changes import (
    STAGE_ENACTED,
    get_dossier_changed_articles,
)
from lawgraph.db.queries.dossiers import (
    DossierFilters,
    count_dossier_members,
    enrich_dossier_docs,
    get_dossier_by_number,
    get_dossier_documents,
    get_dossier_hub,
    get_dossier_mutations,
    get_dossier_relations,
    get_dossier_timeline,
    get_dossiers,
    get_laws_named,
)

router = APIRouter()

DossierNumber = Annotated[
    str,
    Path(
        description="Dossier number, e.g. 29684, 29684-I, 21501-31 or 36956-(R2220).",
        pattern=DOSSIER_NUMBER_PATTERN,
    ),
]


# What the dossier lists filter on: a number, a dossier, or words of the title.
Subject = Annotated[
    str | None,
    Query(
        description=(
            "A number (``37035``: every dossier of that number), a dossier (``37035-XXII``) "
            "or a substring of the title."
        )
    ),
]


def _dossier_or_404(store: GraphStore, number: str) -> dict[str, Any]:
    dossier = get_dossier_by_number(store, number)
    if dossier is None:
        raise HTTPException(status_code=404, detail=f"Dossier {number} not found.")
    return dossier


_PHASE_NAMES = tuple(p.name for p in PHASES)


class _ListParams:
    """The filters, order and page of a dossier list, as query parameters."""

    def __init__(
        self,
        status: Annotated[
            Literal["open", "closed", "all"],
            Query(description="Open dossiers, closed ones (with an outcome) or both."),
        ] = "all",
        outcome: Annotated[DossierOutcome | None, Query()] = None,
        kind: Annotated[
            str | None,
            Query(
                description="Comma-separated kinds (``Zaak.Soort``), e.g. "
                f"``Wetgeving,Begroting``; one of {', '.join(CARRYING_KINDS)}."
            ),
        ] = None,
        number: Annotated[
            str | None,
            Query(
                description="The start of the number: ``36264`` (that number and its "
                "chapters), ``37020-`` (the chapters of 37020).",
                pattern=r"^\d+(-[A-Za-z0-9()]*)?$",
            ),
        ] = None,
        committee: Annotated[str | None, Query(description="Committee slug.")] = None,
        subject: Subject = None,
        phase: Annotated[
            str | None,
            Query(
                description="The dossier's current phase, e.g. ``Verslag``. To filter on "
                "a phase being done at all, use ``has_phase``."
            ),
        ] = None,
        has_phase: Annotated[
            str | None,
            Query(
                description="Comma-separated phases; only dossiers that have done all of "
                "them, e.g. ``Memorie van toelichting,Advies Raad van State``."
            ),
        ] = None,
        ministry: Annotated[
            MinistryKey | None, Query(description="The ministry that brought it in.")
        ] = None,
        initiative: Annotated[
            bool | None,
            Query(
                description="True: brought in by a Kamerlid; false: by the government."
            ),
        ] = None,
        opened_from: Annotated[
            dt.date | None, Query(description="Opened on or after this day.")
        ] = None,
        opened_to: Annotated[
            dt.date | None, Query(description="Opened on or before this day.")
        ] = None,
        sort: Annotated[
            Literal["number", "opened_on", "closed_on", "title"] | None,
            Query(
                description="``number`` in the order of the Kamer, ``opened_on`` and "
                "``closed_on`` newest first, ``title`` alphabetically; ties by key. "
                "Default ``number`` with a ``number`` filter, else ``opened_on``."
            ),
        ] = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> None:
        self.filters = DossierFilters(
            status=None if status == "all" else status,
            outcome=outcome,
            kinds=parse_choices(kind, CARRYING_KINDS, "kind"),
            phase=(parse_choices(phase, _PHASE_NAMES, "phase") or (None,))[0],
            has_phase=parse_choices(has_phase, _PHASE_NAMES, "has_phase"),
            ministry=ministry.value if ministry else None,
            initiative=initiative,
            number=number,
            subject=subject,
            committee_slug=committee,
            opened_from=opened_from.isoformat() if opened_from else None,
            opened_to=opened_to.isoformat() if opened_to else None,
        )
        self.sort = sort or ("number" if number else "opened_on")
        self.limit = limit
        self.offset = offset


def _list(store: GraphStore, params: _ListParams) -> DossierListResponse:
    raw = get_dossiers(
        store,
        params.filters,
        sort=params.sort,
        limit=params.limit,
        offset=params.offset,
    )
    docs = raw.get("items") or []
    enrich_dossier_docs(store, docs)
    return DossierListResponse(
        total=int(raw.get("total") or 0),
        items=[DossierSummaryDTO.from_document(d) for d in docs],
        facets=DossierFacetsDTO(**raw.get("facets") or {}),
    )


_LIST_DESCRIPTION = (
    "``total`` is the absolute count, independent of ``limit``. ``facets`` counts the "
    "dossiers per status, outcome, track, current stage and ministry under the other "
    "filters, each dimension without its own filter."
)


@router.get(
    "",
    response_model=DossierListResponse,
    summary="Dossiers",
    description=(
        "Every dossier, open and closed, filtered by status, outcome, track, the start of "
        "its number, committee, subject (a number, a dossier, or words of the title, such "
        "as its short title), stage, ministry, initiative and the day it opened. "
        + _LIST_DESCRIPTION
    ),
    tags=["dossiers"],
)
def list_dossiers(
    store: Annotated[GraphStore, Depends(get_store)],
    params: Annotated[_ListParams, Depends()],
) -> DossierListResponse:
    return _list(store, params)


@router.get(
    "/{number}",
    response_model=DossierDetailResponse,
    summary="Dossier detail",
    description=(
        "One dossier: its title, stage, how many documents, activities, "
        "decisions and commitments it holds, and what it links to: the "
        "instruments it legislated, amends, introduces or repeals (one item per "
        "instrument, relation and status), the committees that lead its "
        "activities, its documents per kind, its Eerste Kamer papers, and the dossiers it "
        "revises, accompanies or is related to (and those that revise, accompany or "
        "relate to it)."
    ),
    tags=["dossiers"],
)
def get_dossier(
    number: DossierNumber,
    store: Annotated[GraphStore, Depends(get_store)],
) -> DossierDetailResponse:
    dossier = _dossier_or_404(store, number)
    enrich_dossier_docs(store, [dossier])
    relations = get_dossier_relations(store, dossier["_id"])
    enrich_dossier_docs(store, [row["dossier"] for row in relations])
    return DossierDetailResponse.from_document(
        dossier,
        counts=count_dossier_members(store, dossier["_id"]),
        hub=get_dossier_hub(store, dossier["_id"]),
        relations=relations,
        laws_named=get_laws_named(
            store, laws_in_title((dossier.get("props") or {}).get("title"))
        ),
    )


@router.get(
    "/{number}/documents",
    response_model=DossierDocumentsResponse,
    summary="Dossier documents",
    description=(
        "The documents in this dossier — linked directly or through a case — "
        "newest first. ``total`` is the absolute count."
    ),
    tags=["dossiers"],
)
def list_dossier_documents(
    number: DossierNumber,
    store: Annotated[GraphStore, Depends(get_store)],
    limit: Annotated[int, Query(ge=1, le=200)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DossierDocumentsResponse:
    dossier = _dossier_or_404(store, number)
    raw = get_dossier_documents(store, dossier["_id"], limit=limit, offset=offset)
    return DossierDocumentsResponse(
        total=int(raw.get("total") or 0),
        items=[DossierDocumentDTO.from_row(d) for d in raw.get("items") or []],
    )


@router.get(
    "/{number}/timeline",
    response_model=DossierTimelineResponse,
    summary="Dossier timeline",
    description=(
        "Documents, activities, decisions and commitments in date order, "
        "newest first by default. Filter with ``?kind=motie,amendement``."
    ),
    tags=["dossiers"],
)
def get_timeline(
    number: DossierNumber,
    store: Annotated[GraphStore, Depends(get_store)],
    order: Annotated[Literal["asc", "desc"], Query(description="Date order.")] = "desc",
    kind: Annotated[
        str | None, Query(description="Comma-separated document kinds.")
    ] = None,
    include_planned: Annotated[
        bool,
        Query(description="False leaves out the activities with status ``Gepland``."),
    ] = True,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
) -> DossierTimelineResponse:
    dossier = _dossier_or_404(store, number)
    rows = get_dossier_timeline(
        store,
        dossier["_id"],
        order=order,
        kind_filter=[k.strip() for k in kind.split(",")] if kind else None,
        include_planned=include_planned,
        limit=limit,
    )
    entries = [timeline_entry(row) for row in rows]
    return DossierTimelineResponse(
        number=number, total=len(entries), order=order, entries=entries
    )


@router.get(
    "/{number}/changed-articles",
    response_model=DossierChangedArticlesResponse,
    summary="The articles a bill changes",
    description=(
        "Per law, the articles this dossier amends, introduces or repeals, each with "
        "its `stage`: `enacted`, by a publication legislated in the dossier (with its "
        "`official_id` and the `effective_date` of the change), or `proposed`, by a "
        "paper of the dossier (a bill, an amendment). Citations and explanations are no "
        "change; `/mutations` has the graph of all of them."
    ),
    tags=["dossiers"],
)
def get_changed_articles(
    number: DossierNumber,
    store: Annotated[GraphStore, Depends(get_store)],
) -> DossierChangedArticlesResponse:
    dossier = _dossier_or_404(store, number)
    laws = [
        DossierChangedLaw(
            law=found["law"],
            total=len(found["changes"]),
            changes=[DossierChange.from_row(c) for c in found["changes"]],
        )
        for found in get_dossier_changed_articles(store, dossier["_id"])
    ]
    changes = [c for law in laws for c in law.changes]
    enacted = sum(c.stage == STAGE_ENACTED for c in changes)
    return DossierChangedArticlesResponse(
        number=number,
        total=len(changes),
        articles=len({c.article.id for c in changes}),
        enacted=enacted,
        proposed=len(changes) - enacted,
        laws=laws,
    )


@router.get(
    "/{number}/mutations",
    response_model=DossierMutationsResponse,
    summary="Dossier mutation graph",
    description=(
        "The nodes and edges by which this dossier proposes to change the "
        "law, shaped like the graph endpoint so the frontend can render it "
        "directly."
    ),
    tags=["dossiers"],
)
def get_mutations(
    number: DossierNumber,
    store: Annotated[GraphStore, Depends(get_store)],
) -> DossierMutationsResponse:
    dossier = _dossier_or_404(store, number)
    raw = get_dossier_mutations(store, dossier["_id"])
    return DossierMutationsResponse(
        number=number,
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

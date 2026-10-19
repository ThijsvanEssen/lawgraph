"""Dossier endpoints.

GET /api/dossiers                      — every dossier, with filters, order and facets
GET /api/dossiers/{number}             — one dossier with its counts
GET /api/dossiers/{number}/documents   — its documents
GET /api/dossiers/{number}/timeline    — everything that happened, in order
GET /api/dossiers/{number}/amendments  — its amendments as the Kamer handled them
GET /api/dossiers/{number}/mutations   — its pending-change subgraph
GET /api/dossiers/{number}/changed-articles — the articles it changes, per law
GET /api/parties/colors                — party colours for the frontend
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, Path, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.params import (
    DOSSIER_NUMBER_PATTERN,
    DOSSIER_PREFIX_PATTERN,
    ListLimit,
    MinistryKey,
    PageLimit,
    parse_choices,
)
from lawgraph.api.schemas.amendments import AmendmentChainsResponse, amendment_chains
from lawgraph.api.schemas.dossier_changes import (
    DossierChange,
    DossierChangedArticlesResponse,
    DossierChangedLaw,
)
from lawgraph.api.schemas.dossiers import (
    DossierDetailResponse,
    DossierDocumentDTO,
    DossierDocumentsResponse,
    DossierFacetsDTO,
    DossierListResponse,
    DossierMutationEdge,
    DossierMutationNode,
    DossierMutationsResponse,
    DossierSummaryDTO,
    DossierTimelineResponse,
    legal_effect,
    timeline_entry,
)
from lawgraph.core.dossier_stages import CARRYING_KINDS, PHASES
from lawgraph.core.law_names import laws_in_title
from lawgraph.core.relations import without_unknown_relations
from lawgraph.core.time import dutch_today, iso_day
from lawgraph.core.votes import VoteOutcome
from lawgraph.db import GraphStore
from lawgraph.db.queries._helpers import run_together
from lawgraph.db.queries.amendments import get_amendment_chains
from lawgraph.db.queries.documents import get_replacements
from lawgraph.db.queries.dossier_changes import (
    STAGE_ENACTED,
    get_dossier_changed_articles,
)
from lawgraph.db.queries.dossiers import (
    DossierFilters,
    TimelineOrder,
    count_dossier_members,
    enrich_dossier_docs,
    get_dossier_by_number,
    get_dossier_documents,
    get_dossier_hub,
    get_dossier_implements,
    get_dossier_mutations,
    get_dossier_relations,
    get_dossier_timeline,
    get_dossiers,
    get_instrument_names,
    get_next_activity,
)
from lawgraph.db.queries.law_names import get_laws_named
from lawgraph.db.queries.not_found import require

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


_PHASE_NAMES = tuple(p.name for p in PHASES)


class DossierListParams:
    """The filters, order and page of a dossier list, as query parameters."""

    def __init__(
        self,
        status: Annotated[
            Literal["open", "closed", "all"],
            Query(description="Open dossiers, closed ones (with an outcome) or both."),
        ] = "all",
        outcome: Annotated[VoteOutcome | None, Query()] = None,
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
                pattern=DOSSIER_PREFIX_PATTERN,
            ),
        ] = None,
        committee: Annotated[str | None, Query(description="Committee slug.")] = None,
        subject: Subject = None,
        phase: Annotated[
            str | None,
            Query(
                description="Comma-separated: the dossiers whose current phase is one of "
                "them, e.g. ``Verslag`` or ``Stemmingen,Eindtekst``. To filter on a phase "
                "being done at all, use ``has_phase``."
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
            Literal["number", "opened_on", "last_activity", "closed_on", "title"]
            | None,
            Query(
                description="``number`` in the order of the Kamer, ``opened_on``, "
                "``last_activity`` and ``closed_on`` newest first, ``title`` "
                "alphabetically; ties by key. "
                "Default ``number`` with a ``number`` filter, else ``opened_on``."
            ),
        ] = None,
        limit: ListLimit = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
        facets: Annotated[
            bool,
            Query(description="Count per status, outcome, track, stage and ministry."),
        ] = True,
    ) -> None:
        self.filters = DossierFilters(
            status=None if status == "all" else status,
            outcome=outcome,
            kinds=parse_choices(kind, CARRYING_KINDS, "kind"),
            phases=parse_choices(phase, _PHASE_NAMES, "phase"),
            has_phase=parse_choices(has_phase, _PHASE_NAMES, "has_phase"),
            ministry=ministry.value if ministry else None,
            initiative=initiative,
            number=number,
            subject=subject,
            committee_slug=committee,
            opened_from=iso_day(opened_from),
            opened_to=iso_day(opened_to),
        )
        self.sort = sort or ("number" if number else "opened_on")
        self.limit = limit
        self.offset = offset
        self.facets = facets


def dossier_list(store: GraphStore, params: DossierListParams) -> DossierListResponse:
    raw = get_dossiers(
        store,
        params.filters,
        sort=params.sort,
        limit=params.limit,
        offset=params.offset,
        facets=params.facets,
    )
    docs = raw.get("items") or []
    enrich_dossier_docs(store, docs)
    return DossierListResponse(
        total=int(raw.get("total") or 0),
        items=[DossierSummaryDTO.from_document(d) for d in docs],
        facets=DossierFacetsDTO(**raw.get("facets") or {}) if params.facets else None,
    )


_LIST_DESCRIPTION = (
    "``total`` is the absolute count, independent of ``limit``. ``facets`` counts the "
    "dossiers per status, outcome, track, current stage and ministry under the other "
    "filters, each dimension without its own filter; ``facets=false`` leaves them out "
    "(null): the pages after the first need none."
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
        + "\n\n"
        "every dossier, open and closed; `status` (`open`, `closed`, `all`, default "
        "`all`), `outcome`, `kind` (comma-separated, the values of `facets.kind`), `number` (the "
        "start of the label: `36264` gives that dossier and its chapters, `37020-` the "
        "chapters of 37020), `committee` (slug), `subject` (a number, a dossier such "
        "as `37035-XXII`, or words of the title, which holds the short title: "
        "`Verzamelwet gegevensbescherming`), `phase` (the current one; "
        "comma-separated, one of them), `has_phase` (all listed phases done), "
        "`ministry`, `initiative`, `opened_from`, `opened_to` (dates), `sort` "
        "(`number`: in the order of the Kamer, no suffix, numeric suffixes by value, "
        "budget chapters by value with their letter, then the rest (`props.order`); "
        "`opened_on`, `last_activity` and `closed_on` newest first; `title`; ties by "
        "key; default `number` with a `number` filter, else `opened_on`), `limit`, "
        "`offset`; `total` counts every match. `facets`: per `status`, `outcome`, "
        "`kind`, `phase` and `ministry` a list of `{value, count}` under the current "
        "filters, each dimension counted without its own filter, the largest first "
        "(`value` null counts the dossiers without one); `facets=false` gives `facets` "
        "null and counts nothing but `total`, the choice for the pages after the "
        "first. Every dossier summary in the API carries `short_title` (a budget by "
        "its chapter and year, `Begroting Defensie 2027`, a change of it also by its "
        "nota, `Suppletoire begroting gemeentefonds 2026 (Miljoenennota)`, a slotwet "
        "as `Slotwet Defensie 2025`; else the parentheses that end the title, before "
        "where the act it carries out was published: not `PbEU 2022, L 173`, `Trb.`, "
        "`Stb.`), and `ministry` (of the bewindspersoon who signed its earliest signed "
        "document first), `initiative` (a Kamerlid signed first) and `cabinet` (in "
        "office then), null when unknown"
    ),
    tags=["dossiers"],
)
def list_dossiers(
    store: Annotated[GraphStore, Depends(get_store)],
    params: Annotated[DossierListParams, Depends()],
) -> DossierListResponse:
    return dossier_list(store, params)


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
    dossier = require(get_dossier_by_number(store, number), "Dossier", number)
    enrich_dossier_docs(store, [dossier])
    dossier_id = dossier["id"]
    title = (dossier.get("props") or {}).get("title")

    def related() -> list[dict[str, Any]]:
        relations = get_dossier_relations(store, dossier_id)
        enrich_dossier_docs(store, [row["dossier"] for row in relations])
        return relations

    # independent reads, side by side: the answer takes as long as the slowest
    answers: list[Any] = run_together(
        related,
        lambda: get_dossier_hub(store, dossier_id),
        lambda: get_dossier_implements(store, dossier_id),
        lambda: count_dossier_members(store, dossier_id),
        lambda: get_laws_named(store, laws_in_title(title)),
        lambda: get_next_activity(store, dossier_id, dutch_today().isoformat()),
    )
    relations, hub, implements, counts, laws_named, next_activity = answers
    hub_rows = list(hub.get("instruments") or [])
    names = get_instrument_names(
        store, sorted({row["id"] for row in [*hub_rows, *implements]})
    )
    return DossierDetailResponse.from_document(
        dossier,
        counts=counts,
        hub=hub,
        legal_effect=legal_effect(hub_rows, implements, names, title),
        relations=relations,
        laws_named=laws_named,
        next_activity=next_activity,
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
    limit: PageLimit = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> DossierDocumentsResponse:
    dossier = require(get_dossier_by_number(store, number), "Dossier", number)
    raw = get_dossier_documents(store, dossier["id"], limit=limit, offset=offset)
    items = raw.get("items") or []
    chains = get_replacements(store, [d["id"] for d in items])
    return DossierDocumentsResponse(
        total=int(raw.get("total") or 0),
        items=[DossierDocumentDTO.from_row(d, chains.get(d["id"])) for d in items],
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
    order: Annotated[TimelineOrder, Query(description="Date order.")] = "desc",
    kind: Annotated[
        str | None, Query(description="Comma-separated document kinds.")
    ] = None,
    include_planned: Annotated[
        bool,
        Query(description="False leaves out the activities with status ``Gepland``."),
    ] = True,
    limit: ListLimit = 100,
) -> DossierTimelineResponse:
    dossier = require(get_dossier_by_number(store, number), "Dossier", number)
    rows = get_dossier_timeline(
        store,
        dossier["id"],
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
    "/{number}/amendments",
    response_model=AmendmentChainsResponse,
    summary="Dossier amendments",
    description=(
        "Its amendments as the Kamer handled them: each chain of papers that replace each "
        "other (``REVISES``; chains that meet in one last paper are one, ``merged``) "
        "whose last paper is a paper of the dossier, with its papers, who submitted it, "
        "the decision that decides it and its outcome, the oldest first. From "
        "``lg_amendment_chains``, as ``lawgraph feed-events`` last wrote it (after every "
        "poll), as ``amendment_chains`` of ``/api/feed/periods`` counts them."
    ),
    tags=["dossiers"],
)
def list_dossier_amendments(
    number: DossierNumber,
    store: Annotated[GraphStore, Depends(get_store)],
) -> AmendmentChainsResponse:
    dossier = require(get_dossier_by_number(store, number), "Dossier", number)
    return amendment_chains(number, get_amendment_chains(store, dossier["id"]))


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
    dossier = require(get_dossier_by_number(store, number), "Dossier", number)
    laws = [
        DossierChangedLaw(
            law=found["law"],
            total=len(found["changes"]),
            changes=[DossierChange.from_row(c) for c in found["changes"]],
        )
        for found in get_dossier_changed_articles(store, dossier["id"])
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
    dossier = require(get_dossier_by_number(store, number), "Dossier", number)
    raw = get_dossier_mutations(store, dossier["id"])
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
            for e in without_unknown_relations(
                raw.get("edges", []), lambda e: e.get("relation")
            )
        ],
    )

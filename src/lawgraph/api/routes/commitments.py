"""Commitment endpoints.

GET /api/commitments        — commitments, filtered and paged
GET /api/commitments/{key}  — one commitment
"""

from __future__ import annotations

import datetime as dt
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.params import ListLimit, MinistryKey
from lawgraph.api.schemas.commitments import (
    CommitmentDTO,
    CommitmentFacetsDTO,
    CommitmentListResponse,
)
from lawgraph.core.time import iso_day
from lawgraph.db import GraphStore
from lawgraph.db.queries.commitments import get_commitment, get_commitments
from lawgraph.db.queries.not_found import require
from lawgraph.db.queries.search.clause import queries_words

router = APIRouter()


@router.get(
    "",
    response_model=CommitmentListResponse,
    summary="Commitments",
    description=(
        "Commitments (toezeggingen) of bewindspersonen, paged; ``total`` counts every "
        "match. ``status`` is the Toezegging.Status of the Tweede Kamer (`Openstaand`, "
        "`Afgedaan`, `Nagekomen`, `Niet nagekomen`, `Deels Afgedaan`, `Vervallen`). "
        "``overdue`` keeps the `Openstaand` ones whose expected date has passed. "
        "``facets`` counts per ``status``, ``cabinet`` and ``ministry`` the commitments "
        "under the other filters; ``facets=false`` leaves them out (null): the pages after "
        "the first need none."
    ),
    tags=["government"],
)
def list_commitments(
    store: Annotated[GraphStore, Depends(get_store)],
    status: Annotated[
        str | None,
        Query(
            description="A Toezegging.Status as the Tweede Kamer writes it: `Openstaand`."
        ),
    ] = None,
    member: Annotated[str | None, Query(description="Member key.")] = None,
    cabinet: Annotated[str | None, Query(description="Cabinet key.")] = None,
    ministry: Annotated[MinistryKey | None, Query()] = None,
    dossier: Annotated[
        str | None, Query(description="A dossier number or label: 36600, 36600-VII.")
    ] = None,
    due_before: Annotated[
        dt.date | None, Query(description="Expected before this day.")
    ] = None,
    overdue: Annotated[bool, Query()] = False,
    date_from: Annotated[
        dt.date | None,
        Query(alias="from", description="Made on or after this day, YYYY-MM-DD."),
    ] = None,
    date_to: Annotated[
        dt.date | None,
        Query(alias="to", description="Made on or before this day, YYYY-MM-DD."),
    ] = None,
    q: Annotated[
        str | None,
        Query(
            description="Words of the text or number, every one, in any order and any "
            "case, as ``/api/search`` finds a commitment: its stop words left out unless "
            "they are all of it, a word also by its stem of four characters or more; each "
            "from the start of a word, one of at most four characters as a whole word."
        ),
    ] = None,
    sort: Annotated[
        Literal["date", "expected_resolution"],
        Query(description="Newest made first, or soonest due first."),
    ] = "date",
    limit: ListLimit = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    facets: Annotated[
        bool, Query(description="Count per status, cabinet and ministry.")
    ] = True,
) -> CommitmentListResponse:
    raw = get_commitments(
        store,
        status=status,
        member=member,
        cabinet=cabinet,
        ministry=ministry.value if ministry else None,
        dossier=dossier,
        due_before=iso_day(due_before),
        overdue=overdue,
        q=queries_words(store, (q,) if q else ()),
        sort=sort,
        limit=limit,
        offset=offset,
        made_from=iso_day(date_from),
        made_to=iso_day(date_to),
        facets=facets,
    )
    return CommitmentListResponse(
        total=int(raw.get("total") or 0),
        items=[CommitmentDTO.from_row(row) for row in raw.get("items") or []],
        facets=CommitmentFacetsDTO(**(raw.get("facets") or {})) if facets else None,
    )


@router.get(
    "/{key}",
    response_model=CommitmentDTO,
    summary="Commitment detail",
    tags=["government"],
)
def get_commitment_detail(
    key: str,
    store: Annotated[GraphStore, Depends(get_store)],
) -> CommitmentDTO:
    row = require(get_commitment(store, key), "Commitment", key)
    return CommitmentDTO.from_row(row)

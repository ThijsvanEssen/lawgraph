"""Ministry endpoints.

GET /api/ministries        — every ministry, in protocol order
GET /api/ministries/{key}  — one ministry with its bewindspersonen and what is its own
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from lawgraph.api.dependencies import get_store
from lawgraph.api.schemas.ministries import MinistryDetailDTO, MinistryDTO
from lawgraph.core.ministries import MINISTRIES, MINISTRY_BY_KEY
from lawgraph.core.tk_records.commitments import COMMITMENT_OPEN
from lawgraph.db import GraphStore
from lawgraph.db.queries.cabinets import ministry_posts
from lawgraph.db.queries.commitments import get_commitments
from lawgraph.db.queries.dossiers import DossierFilters, get_dossiers
from lawgraph.db.queries.instruments import get_instruments_list
from lawgraph.db.queries.not_found import require

router = APIRouter()


@router.get(
    "",
    response_model=list[MinistryDTO],
    summary="Ministries",
    description=(
        "Every ministry a post, a dossier or a commitment can name, in protocol order; a "
        "former ministry (``Verkeer en Waterstaat``) follows its successor and names it. "
        "From ``data/ministries.json``: TOOI since about 2010 (with the decree of each "
        "change), the Rijksoverheid cabinet pages before; ``periods`` say which."
    ),
    tags=["government"],
)
def list_ministries() -> list[MinistryDTO]:
    return [MinistryDTO.from_ministry(m) for m in MINISTRIES]


@router.get(
    "/{key}",
    response_model=MinistryDetailDTO,
    summary="Ministry detail",
    description=(
        "One ministry: its names (``periods``, ``predecessors``), its bewindspersonen per "
        "cabinet, newest first (``cabinets``), and the counts of what is its own, each the "
        "``total`` of a list filtered on ``ministry``: ``laws`` (the BWB regulations in "
        "force it is first responsible for, ``/api/instruments``), ``open_dossiers`` "
        "(``/api/dossiers?status=open``) and ``open_commitments`` "
        "(``/api/commitments?status=Openstaand``)."
    ),
    tags=["government"],
)
def get_ministry(
    key: str,
    store: Annotated[GraphStore, Depends(get_store)],
) -> MinistryDetailDTO:
    ministry = require(MINISTRY_BY_KEY.get(key), "Ministry", key)
    laws = get_instruments_list(store, ministry=key, limit=1, facets=False)
    dossiers = get_dossiers(
        store, DossierFilters(status="open", ministry=key), limit=1, facets=False
    )
    commitments = get_commitments(
        store, status=COMMITMENT_OPEN, ministry=key, limit=1, facets=False
    )
    return MinistryDetailDTO.from_detail(
        ministry,
        ministry_posts(store, key),
        {
            "laws": int(laws.get("total") or 0),
            "open_dossiers": int(dossiers.get("total") or 0),
            "open_commitments": int(commitments.get("total") or 0),
        },
    )

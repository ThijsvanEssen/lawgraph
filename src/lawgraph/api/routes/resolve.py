from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.schemas.resolve import ResolveResponse
from lawgraph.db import ArangoStore
from lawgraph.db.queries.resolve import resolve as resolve_query

router = APIRouter()


@router.get(
    "",
    response_model=ResolveResponse,
    summary="Resolve a citation, identifier or law name to one node",
    description=(
        "Reads `q` as a citation (`art. 6:162 BW`, `artikel 287 Sr`, `Sr 287`), an "
        "identifier (ECLI, BWB id, CELEX id), a Kamerstuk (`36327`, `36327-3`, "
        "`Kamerstukken II 2020/21, 36327, nr. 3`) or the name of a law, and answers with "
        "the one best match (`id`, `key`, `collection`) and up to five alternatives. "
        "`confidence` says how sure the match is. Nothing that fits answers 200 with "
        "kind `none` and no match: the query is then words for `/api/search`."
    ),
    tags=["resolve"],
)
def resolve(
    q: Annotated[
        str, Query(min_length=1, max_length=200, description="Citation or name")
    ],
    store: Annotated[ArangoStore, Depends(get_store)],
) -> ResolveResponse:
    return ResolveResponse(q=q, **resolve_query(store, q))

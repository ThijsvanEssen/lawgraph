"""``GET /api/lookup``: the node a readable URL names, exactly, or 404 ``not_in_data``."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.schemas.lookup import LookupKind, LookupResponse
from lawgraph.db import GraphStore
from lawgraph.db.queries import lookup

router = APIRouter()

NOT_IN_DATA = "not_in_data"

# collection -> the kind of node it holds
_KIND_OF = {
    "documents": "document",
    "dossiers": "dossier",
    "articles": "article",
    "annexes": "annex",
    "cases": "case",
    "instruments": "instrument",
    "judgments": "judgment",
    "commitments": "commitment",
    "factions": "faction",
    "committees": "committee",
    "cabinets": "cabinet",
    "members": "member",
}


def _need(**params: str | None) -> dict[str, str]:
    """The parameters a kind needs; 422 when one is missing."""
    missing = [name for name, value in params.items() if not (value or "").strip()]
    if missing:
        raise HTTPException(status_code=422, detail=f"missing: {', '.join(missing)}")
    return {name: (value or "").strip() for name, value in params.items()}


def _finder(
    store: GraphStore,
    kind: LookupKind,
    p: dict[str, str | None],
) -> Callable[[], str | None]:
    """How *kind* is looked up, with its parameters checked."""
    if kind == "document":
        a = _need(dossier=p["dossier"], number=p["number"])
        return lambda: lookup.find_document(store, a["dossier"], a["number"])
    if kind == "dossier":
        a = _need(number=p["number"])
        return lambda: lookup.find_dossier(store, a["number"])
    if kind == "article":
        a = _need(law=p["law"], number=p["number"])
        return lambda: lookup.find_article(store, a["law"], a["number"])
    if kind == "annex":
        a = _need(law=p["law"], label=p["label"])
        return lambda: lookup.find_annex(store, a["law"], a["label"])
    if kind == "case":
        a = _need(number=p["number"])
        return lambda: lookup.find_case(store, a["number"])
    if kind == "judgment":
        a = _need(ecli=p["ecli"])
        return lambda: lookup.find_judgment(store, a["ecli"])
    if kind == "publication":
        a = _need(series=p["series"], year=p["year"], number=p["number"])
        if a["series"].lower() not in lookup.SERIES or not (
            a["year"].isdigit() and a["number"].isdigit()
        ):
            raise HTTPException(
                status_code=422, detail="series stb|stcrt|trb, year and number digits"
            )
        return lambda: lookup.find_publication(
            store, a["series"].lower(), a["year"], a["number"]
        )
    if kind == "commitment":
        a = _need(number=p["number"])
        return lambda: lookup.find_commitment(store, a["number"])
    a = _need(id=p["id"])
    by_id: dict[str, Callable[[GraphStore, str], str | None]] = {
        "law": lookup.find_law,
        "official": lookup.find_official,
        "faction": lookup.find_faction,
        "committee": lookup.find_committee,
        "cabinet": lookup.find_cabinet,
        "member": lookup.find_member,
    }
    return lambda: by_id[kind](store, a["id"])


@router.get(
    "",
    response_model=LookupResponse,
    summary="The node a readable URL names, exactly",
    description=(
        "No guess and no fallback (that is `/api/resolve`): the node, or 404 with detail "
        "`not_in_data`. 422 for a parameter that is missing or malformed. `kind` and its "
        "parameters: `document` (`dossier` as in the URL, `36600-VIII`, and `number`, a "
        "number of the Tweede Kamer or a letter of the Eerste Kamer; a paper that is not "
        "there is 404, not its dossier), `dossier` (`number`, `36455-(R2188)`), `article` "
        "(`law` BWB id or CELEX, `number`: `6:162` and `162` under BW Boek 6 alike), "
        "`annex` (`law` BWB id and `label`, `II`), `case` (a zaak of the Tweede Kamer: its "
        "`number`, `2025Z15468`), `law` (`id`), `judgment` (`ecli`; a judgment only "
        "cited is answered, with `stub`), `publication` (`series` stb, stcrt or trb, "
        "`year`, `number`), "
        "`official` (`id` of officielebekendmakingen.nl: `stb-2026-94`, `kst-36799-31`), "
        "`commitment` (`number`), `faction`, `committee` (slug), `cabinet` and `member` "
        "(its `slug`, `rob-jetten`) (`id`)."
    ),
    tags=["lookup"],
)
def get_lookup(
    store: Annotated[GraphStore, Depends(get_store)],
    kind: Annotated[LookupKind, Query()],
    dossier: Annotated[str | None, Query()] = None,
    number: Annotated[str | None, Query()] = None,
    law: Annotated[str | None, Query()] = None,
    label: Annotated[str | None, Query()] = None,
    ecli: Annotated[str | None, Query()] = None,
    series: Annotated[str | None, Query()] = None,
    year: Annotated[str | None, Query()] = None,
    id: Annotated[str | None, Query()] = None,  # noqa: A002 - the name of the parameter
) -> LookupResponse:
    params = {
        "dossier": dossier,
        "number": number,
        "law": law,
        "label": label,
        "ecli": ecli,
        "series": series,
        "year": year,
        "id": id,
    }
    node_id = _finder(store, kind, params)()
    if node_id is None:
        raise HTTPException(status_code=404, detail=NOT_IN_DATA)
    found = lookup.answer(store, node_id)
    props = found["props"]
    return LookupResponse(
        id=found["id"],
        key=found["key"],
        collection=found["collection"],
        kind=_KIND_OF.get(found["collection"], found["type"]),
        display_name=props.get("display_name"),
        chamber=found["chamber"],
        stub=props.get("stub") is True,
        props={k: v for k, v in props.items() if k not in ("display_name", "stub")},
    )

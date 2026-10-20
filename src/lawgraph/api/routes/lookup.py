"""``GET /api/lookup``: the node a readable URL names, exactly, or 404."""

from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from lawgraph.api.dependencies import get_store
from lawgraph.api.errors import Invalid
from lawgraph.api.schemas.lookup import LookupKind, LookupResponse
from lawgraph.api.schemas.nodes import node_type_of
from lawgraph.core.publications import SERIES, publication_series
from lawgraph.db import GraphStore
from lawgraph.db.queries import lookup
from lawgraph.db.queries.not_found import NotFound

router = APIRouter()


def _need(params: dict[str, str | None], names: tuple[str, ...]) -> list[str]:
    """The values of the parameters *names*, in their order; 422 when one is missing."""
    missing = [name for name in names if not (params[name] or "").strip()]
    if missing:
        raise Invalid(tuple(missing), "missing.")
    return [(params[name] or "").strip() for name in names]


def _find_publication(
    store: GraphStore, series: str, year: str, number: str
) -> str | None:
    """``lookup.find_publication`` with its parameters checked: 422 for another series or
    a year or number that is not digits."""
    known = publication_series(series)
    if known is None:
        raise Invalid("series", f"unknown {series}. Allowed: {', '.join(SERIES)}.")
    wrong = tuple(
        name
        for name, value in (("year", year), ("number", number))
        if not value.isdigit()
    )
    if wrong:
        raise Invalid(wrong, "digits only.")
    return lookup.find_publication(store, known, year, number)


# kind -> the parameters it is looked up by, and the finder they are passed to in order
FINDERS: dict[LookupKind, tuple[tuple[str, ...], Callable[..., str | None]]] = {
    "document": (("dossier", "number"), lookup.find_document),
    "dossier": (("number",), lookup.find_dossier),
    "article": (("law", "number"), lookup.find_article),
    "annex": (("law", "label"), lookup.find_annex),
    "case": (("number",), lookup.find_case),
    "activity": (("number",), lookup.find_activity),
    "judgment": (("ecli",), lookup.find_judgment),
    "publication": (("series", "year", "number"), _find_publication),
    "commitment": (("number",), lookup.find_commitment),
    "law": (("id",), lookup.find_law),
    "official": (("id",), lookup.find_official),
    "faction": (("id",), lookup.find_faction),
    "committee": (("id",), lookup.find_committee),
    "cabinet": (("id",), lookup.find_cabinet),
    "member": (("id",), lookup.find_member),
}


@router.get(
    "",
    response_model=LookupResponse,
    summary="The node a readable URL names, exactly",
    description=(
        "No guess and no fallback (that is `/api/resolve`): the node, or 404 (`<Kind> "
        "'<its parameters>' not found.`). 422 for a parameter that is missing or "
        "malformed. `kind` and its parameters: `document` (`dossier` as in the URL, "
        "`36600-VIII`, and `number`, a "
        "number of the Tweede Kamer or a letter of the Eerste Kamer; a paper that is not "
        "there is 404, not its dossier), `dossier` (`number`, `36455-(R2188)`), `article` "
        "(`law` BWB id or CELEX, or the abbreviation a law is cited by in any case: `wft`, "
        "`Sr`, `AVG`, and `bw` with the book in the number; `number`: `6:162` and `162` "
        "under BW Boek 6 alike), "
        "`annex` (`law` BWB id and `label`, `II`), `case` (a zaak of the Tweede Kamer: its "
        "`number`, `2025Z15468`), `activity` (one of the Tweede Kamer, a debate: its "
        "`number`, `2026A01323`), `law` (`id`, as `law` of an article), `judgment` "
        "(`ecli`; a judgment only "
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
    names, find = FINDERS[kind]
    values = _need(params, names)
    node_id = find(store, *values)
    found = lookup.answer(store, node_id) if node_id is not None else None
    if found is None:
        raise NotFound(kind.capitalize(), ", ".join(values))
    props = found["props"]
    return LookupResponse(
        id=found["id"],
        key=found["key"],
        collection=found["collection"],
        kind=node_type_of(found["collection"]) or found["type"],
        display_name=props.get("display_name"),
        chamber=found["chamber"],
        stub=props.get("stub") is True,
        props={k: v for k, v in props.items() if k not in ("display_name", "stub")},
    )

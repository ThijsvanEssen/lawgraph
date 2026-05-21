"""Parlement-level endpoints — composition of the Tweede Kamer."""

from __future__ import annotations

import datetime as dt
from typing import Annotated

from fastapi import APIRouter, Depends

from lawgraph.api.dependencies import get_store
from lawgraph.api.queries import get_all_fracties
from lawgraph.api.schemas import PARTY_COLORS, FractieZetelDTO, ParlementZetelsResponse
from lawgraph.db import ArangoStore

router = APIRouter()

TOTAL_PARLIAMENT_SEATS: int = 150

# Conventional left-to-right seating order in the Tweede Kamer hemicycle.
# Keyed by fractie key (make_node_key of the afkorting). Fracties not listed
# fall to the right end. Maintained by hand — there is no machine-readable
# source for political ideology.
_LEFT_TO_RIGHT_ORDER: tuple[str, ...] = (
    "sp",
    "groenlinks_pvda",
    "pvdd",
    "volt",
    "denk",
    "50plus",
    "d66",
    "cda",
    "christenunie",
    "lid_keijzer",
    "vvd",
    "sgp",
    "bbb",
    "ja21",
    "fvd",
    "pvv",
    "groep_markuszower",
)
_ORDER_INDEX = {key: i for i, key in enumerate(_LEFT_TO_RIGHT_ORDER)}

_COLOR_BY_LOWER = {k.lower(): v for k, v in PARTY_COLORS.items()}


def _resolve_color(afkorting: str | None, naam: str | None) -> str | None:
    for candidate in (afkorting, naam):
        if not candidate:
            continue
        hit = _COLOR_BY_LOWER.get(candidate.lower())
        if hit:
            return hit
    return None


@router.get(
    "/zetels",
    response_model=ParlementZetelsResponse,
    summary="Huidige zetelverdeling van de Tweede Kamer",
    description=(
        "Geeft de actieve fracties met hun huidige zetelaantal terug, gesorteerd "
        "naar de conventionele links-rechts opstelling in de plenaire zaal. "
        "Bedoeld voor het renderen van een hemicycle/half-cirkel weergave."
    ),
    tags=["parlement"],
)
def get_zetels(
    store: Annotated[ArangoStore, Depends(get_store)],
) -> ParlementZetelsResponse:
    docs = get_all_fracties(store, actief=True)
    items: list[FractieZetelDTO] = []
    assigned = 0
    fallback_order = len(_LEFT_TO_RIGHT_ORDER)
    for d in docs:
        props = d.get("props") or {}
        zetels = int(props.get("aantal_zetels") or 0)
        if zetels <= 0:
            continue
        key = d["_key"]
        order = _ORDER_INDEX.get(key, fallback_order)
        if key not in _ORDER_INDEX:
            fallback_order += 1
        items.append(
            FractieZetelDTO(
                id=d["_id"],
                key=key,
                afkorting=props.get("afkorting"),
                naam=props.get("naam"),
                aantal_zetels=zetels,
                color=_resolve_color(props.get("afkorting"), props.get("naam")),
                order=order,
            )
        )
        assigned += zetels

    items.sort(key=lambda x: x.order)

    return ParlementZetelsResponse(
        total_seats=TOTAL_PARLIAMENT_SEATS,
        assigned_seats=assigned,
        as_of=dt.date.today().isoformat(),
        fracties=items,
    )

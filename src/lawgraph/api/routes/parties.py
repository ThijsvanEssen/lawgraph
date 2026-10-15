"""Party endpoints.

GET /api/parties/colors  — the colour of each party, and of each Kamer's factions
"""

from __future__ import annotations

from fastapi import APIRouter

from lawgraph.api.schemas.parties import (
    ChamberColorsDTO,
    ColorSourceDTO,
    PartyColorsResponse,
)
from lawgraph.core.parties import (
    CHAMBER_COLOR_SOURCES,
    CHAMBER_COLORS,
    PARTY_ALIASES,
    PARTY_COLORS,
)

router = APIRouter()


@router.get(
    "/colors",
    response_model=PartyColorsResponse,
    summary="Party colours",
    description=(
        "Party to hex colour, from the parties' own house styles, for rendering vote "
        "chips: `colors` by every name and alias (matched without regard to case), "
        "`aliases` another name of a party -> its name in `colors`; `chambers` the "
        "colours each Kamer draws its factions in, with where they were read. Kept by hand "
        "(`lawgraph curated set party-colors`): no source gives colours as data."
    ),
    tags=["parties"],
)
def get_party_colors() -> PartyColorsResponse:
    return PartyColorsResponse(
        colors={
            **PARTY_COLORS,
            **{alias: PARTY_COLORS[name] for alias, name in PARTY_ALIASES.items()},
        },
        aliases=dict(PARTY_ALIASES),
        chambers={
            chamber: ChamberColorsDTO(
                colors={
                    **colors,
                    **{
                        alias: colors[name]
                        for alias, name in PARTY_ALIASES.items()
                        if name in colors
                    },
                },
                source=ColorSourceDTO(**CHAMBER_COLOR_SOURCES[chamber]),
            )
            for chamber, colors in CHAMBER_COLORS.items()
        },
    )

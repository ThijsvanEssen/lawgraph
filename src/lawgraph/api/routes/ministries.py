"""Ministry endpoints.

GET /api/ministries  — every ministry, in protocol order
"""

from __future__ import annotations

from fastapi import APIRouter

from lawgraph.api.schemas.ministries import MinistryDTO
from lawgraph.core.ministries import MINISTRIES

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

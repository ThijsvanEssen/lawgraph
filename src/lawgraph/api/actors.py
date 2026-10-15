"""What a member and a faction answer alike: the dossiers they authored in and the laws they
change most (``/api/members/{key}/…`` and ``/api/factions/{key}/…``)."""

from __future__ import annotations

from lawgraph.api.schemas.actors import (
    ActorDossierDTO,
    ActorDossiersResponse,
    TouchedInstrumentDTO,
    TouchedInstrumentsResponse,
)
from lawgraph.db import GraphStore
from lawgraph.db.queries.actors import get_actor_dossiers, get_actor_touched_instruments
from lawgraph.db.queries.dossiers import enrich_dossier_docs


def touched_instruments(
    store: GraphStore, actor_id: str, limit: int
) -> TouchedInstrumentsResponse:
    items = get_actor_touched_instruments(store, actor_id, limit=limit)
    return TouchedInstrumentsResponse(
        actor_id=actor_id,
        count=len(items),
        items=[TouchedInstrumentDTO(**item) for item in items],
    )


def actor_dossiers(
    store: GraphStore, actor_id: str, limit: int, offset: int
) -> ActorDossiersResponse:
    raw = get_actor_dossiers(store, actor_id, limit=limit, offset=offset)
    rows = raw.get("items") or []
    enrich_dossier_docs(store, [row["dossier"] for row in rows])
    return ActorDossiersResponse(
        actor_id=actor_id,
        total=int(raw.get("total") or 0),
        items=[ActorDossierDTO.from_row(row) for row in rows],
    )

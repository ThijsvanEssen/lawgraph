"""Activity endpoints: one activity of a chamber (a debate, a hearing, a vote).

GET /api/activities/{key}          — the activity: kind, date, subject, committee, dossiers
GET /api/activities/{key}/records  — what was made in it and what was on its agenda
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from lawgraph.api.dependencies import get_store
from lawgraph.api.schemas.activities import ActivityDTO, ActivityRecordsResponse
from lawgraph.config.constants import COLLECTION_ACTIVITIES
from lawgraph.db import GraphStore
from lawgraph.db.queries.activities import get_activity, get_activity_records
from lawgraph.db.queries.dossiers import load_dossier_names
from lawgraph.db.queries.not_found import NotFound, require

router = APIRouter()


@router.get(
    "/{key}",
    response_model=ActivityDTO,
    summary="Activity detail",
    description=(
        "One activity: its `kind`, `date`, `status`, `agenda_title`, `number` (its "
        "address, `/activiteiten/2026A01323`), its page on tweedekamer.nl, the committee "
        "that leads it (null for a plenary one), the dossiers on its agenda with their "
        "names, and the activities it took the place of or that took its place. What was "
        "made in it is `/records`. 404 when unknown."
    ),
    tags=["activities"],
)
def get_activity_detail(
    key: str,
    store: Annotated[GraphStore, Depends(get_store)],
) -> ActivityDTO:
    row = require(get_activity(store, key), "Activity", key)
    return ActivityDTO.from_row(row, load_dossier_names(store))


@router.get(
    "/{key}/records",
    response_model=ActivityRecordsResponse,
    summary="What was made in an activity",
    description=(
        "What is `MADE_IN` the activity: its `documents` (the stenogram and the verslag "
        "of a debate, its convocatie), the `motions` submitted in it, the `commitments` "
        "made in it and the `decisions` taken in it; and the `cases` on its agenda. Each "
        "with its readable address. 404 when unknown."
    ),
    tags=["activities"],
)
def get_activity_records_route(
    key: str,
    store: Annotated[GraphStore, Depends(get_store)],
) -> ActivityRecordsResponse:
    if not store.has_node(COLLECTION_ACTIVITIES, key):
        raise NotFound("Activity", key)
    activity_id = f"{COLLECTION_ACTIVITIES}/{key}"
    return ActivityRecordsResponse.from_row(
        activity_id, get_activity_records(store, activity_id)
    )

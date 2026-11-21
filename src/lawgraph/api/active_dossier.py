"""The dossier that plays now for a search (``active_dossier`` of ``/api/search``): of the
dossiers it found, one with activity in the last 30 days, with its newest papers, the votes
on its motions, its open commitments and its law, read as the dossier pages read them."""

from __future__ import annotations

import datetime as dt
from typing import Any

from lawgraph.api.schemas.commitments import CommitmentDTO
from lawgraph.api.schemas.common import dossier_names_of
from lawgraph.api.schemas.decisions import DecisionSummaryDTO
from lawgraph.api.schemas.dossiers import DossierDocumentDTO, merge_instruments
from lawgraph.api.schemas.search import ActiveDossierDTO
from lawgraph.core.tk_records.commitments import COMMITMENT_OPEN
from lawgraph.core.tk_records.kinds import KIND_MOTION
from lawgraph.db import GraphStore
from lawgraph.db.queries._helpers import run_together
from lawgraph.db.queries.commitments import get_commitments
from lawgraph.db.queries.decisions import DecisionFilters, get_decisions
from lawgraph.db.queries.dossiers import (
    get_dossier_documents,
    get_dossier_hub,
    load_dossier_names,
)

# A dossier plays when something happened in it this many days back or later.
ACTIVE_DAYS = 30
NEWEST_DOCUMENTS = 3
MOTIONS = 5
COMMITMENTS = 3


def playing(hits: list[dict[str, Any]], today: dt.date) -> dict[str, Any] | None:
    """Of the dossier *hits* of a search, the one whose ``last_activity`` lies in the last
    ``ACTIVE_DAYS`` days: of the best ``score``, then the newest activity, then the first
    key; None when none does."""
    since = (today - dt.timedelta(days=ACTIVE_DAYS)).isoformat()
    active = [h for h in hits if str(h["extra"].get("last_activity") or "") >= since]
    by_key = sorted(active, key=lambda h: str(h["key"]))
    ranked = sorted(
        by_key,
        key=lambda h: (h["score"], str(h["extra"]["last_activity"])),
        reverse=True,
    )
    return ranked[0] if ranked else None


def active_dossier(
    store: GraphStore, hits: list[dict[str, Any]], today: dt.date
) -> ActiveDossierDTO | None:
    """The dossier of *hits* that plays (``playing``) with what plays in it; None when none
    does. Its four reads run side by side."""
    hit = playing(hits, today)
    if hit is None:
        return None
    number = str(hit["extra"]["number"])
    since = (today - dt.timedelta(days=ACTIVE_DAYS)).isoformat()
    motions = DecisionFilters(
        kinds=(KIND_MOTION,), dossier_number=number, from_date=since, unvoted=True
    )
    documents, votes, commitments, hub = run_together(
        lambda: get_dossier_documents(store, hit["id"], limit=NEWEST_DOCUMENTS),
        lambda: get_decisions(store, motions, limit=MOTIONS, facets=False),
        lambda: get_commitments(
            store,
            dossier=number,
            status=COMMITMENT_OPEN,
            limit=COMMITMENTS,
            facets=False,
        ),
        lambda: get_dossier_hub(store, hit["id"], importance=True),
    )
    names = load_dossier_names(store)
    laws = [i for i in merge_instruments(hub.get("instruments") or []) if not i.celex]
    return ActiveDossierDTO(
        id=hit["id"],
        key=hit["key"],
        number=number,
        title=hit.get("display_name"),
        short_title=hit["extra"].get("short_title"),
        last_activity=hit["extra"]["last_activity"],
        documents=[DossierDocumentDTO.from_row(d) for d in documents["items"]],
        document_count=int(documents.get("total") or 0),
        motions=[
            DecisionSummaryDTO(
                **row,
                dossiers=dossier_names_of(row.get("dossier_numbers") or [], names),
            )
            for row in votes["items"]
        ],
        commitments=[CommitmentDTO.from_row(row) for row in commitments["items"]],
        commitment_count=int(commitments.get("total") or 0),
        law=laws[0] if laws else None,
    )

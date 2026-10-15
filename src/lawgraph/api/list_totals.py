"""The total of each list of the explorer without a filter (``/api/stats`` ``lists``): the
``total`` its own route answers for its first page, so the number is the list's own."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from functools import partial

from lawgraph.api.routes import (
    cabinets,
    commitments,
    committees,
    documents,
    dossiers,
    factions,
    instruments,
    judgments,
)
from lawgraph.config.constants import (
    CHAMBER_TK,
    COLLECTION_ACTIVITIES,
    COLLECTION_CABINETS,
    COLLECTION_COMMITMENTS,
    COLLECTION_COMMITTEES,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_EDGES,
    COLLECTION_FACTIONS,
    COLLECTION_INSTRUMENT_VERSIONS,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    COLLECTION_MEMBERS,
)
from lawgraph.db import GraphStore
from lawgraph.db.queries.decisions import DecisionFilters, counted_total
from lawgraph.db.queries.members import count_members
from lawgraph.db.version_cache import cached


@dataclass(frozen=True)
class ListTotal:
    """How a list is counted: ``count`` asks its route as a request without parameters
    would (without the facets where the route still counts its total); the answer is kept
    until one of ``tables`` changes. Without tables the count keeps its own answer."""

    tables: tuple[str, ...]
    count: Callable[[GraphStore], int | None]


LISTS: dict[str, ListTotal] = {
    "instruments": ListTotal(
        (COLLECTION_INSTRUMENTS, COLLECTION_INSTRUMENT_VERSIONS, COLLECTION_EDGES),
        lambda store: (
            instruments.list_instruments(store=store, limit=1, facets=False).total
        ),
    ),
    "judgments": ListTotal(
        (COLLECTION_JUDGMENTS, COLLECTION_EDGES),
        lambda store: (
            judgments.list_judgments(store=store, limit=1, facets=False).total
        ),
    ),
    "dossiers": ListTotal(
        (COLLECTION_DOSSIERS, COLLECTION_DOCUMENTS, COLLECTION_EDGES),
        lambda store: (
            dossiers.dossier_list(
                store, dossiers.DossierListParams(limit=1, facets=False)
            ).total
        ),
    ),
    # with its facets: without them the list gives no total
    "documents": ListTotal(
        (COLLECTION_DOCUMENTS, COLLECTION_EDGES),
        lambda store: documents.list_chamber_documents(store=store, limit=1).total,
    ),
    "members": ListTotal((COLLECTION_MEMBERS,), count_members),
    "bewindspersonen": ListTotal(
        (COLLECTION_MEMBERS,), partial(count_members, government=True)
    ),
    "factions": ListTotal(
        (COLLECTION_FACTIONS, COLLECTION_MEMBERS, COLLECTION_EDGES),
        lambda store: len(factions.list_factions(store=store)),
    ),
    "committees": ListTotal(
        (COLLECTION_COMMITTEES, COLLECTION_EDGES),
        lambda store: len(committees.list_committees(store=store)),
    ),
    "cabinets": ListTotal(
        (
            COLLECTION_CABINETS,
            COLLECTION_MEMBERS,
            COLLECTION_COMMITMENTS,
            COLLECTION_DOSSIERS,
            COLLECTION_EDGES,
        ),
        lambda store: len(cabinets.list_cabinets(store=store)),
    ),
    # the letters that fulfil each commitment of the page (``lg_document_light``)
    "commitments": ListTotal(
        (
            COLLECTION_COMMITMENTS,
            COLLECTION_ACTIVITIES,
            COLLECTION_DOSSIERS,
            COLLECTION_MEMBERS,
            COLLECTION_DOCUMENTS,
            COLLECTION_EDGES,
        ),
        lambda store: (
            commitments.list_commitments(store=store, limit=1, facets=False).total
        ),
    ),
    # as the list opens (the Tweede Kamer), from its kept count without waiting for it:
    # null until it is counted (the warm-up counts it)
    "decisions": ListTotal(
        (), lambda store: counted_total(store, DecisionFilters(chamber=CHAMBER_TK))
    ),
}


def list_totals(store: GraphStore) -> dict[str, int | None]:
    """Per list, the ``total`` it gives without a filter."""
    return {
        name: cached(
            store,
            ("stats list", name),
            partial(entry.count, store),
            tables=entry.tables,
        )
        if entry.tables
        else entry.count(store)
        for name, entry in LISTS.items()
    }

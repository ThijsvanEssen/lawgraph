"""What a poll touched in the Tweede Kamer: for the steps that would otherwise read all.

``semantic tk-government`` and ``semantic tk-dossier-outcomes`` read every dossier and
commitment, since what decides them can change without the dossier's own record changing.
With ``--touched-since`` they read only what was touched since then, and come to the same
for it as a run over all: the commitments, documents, cases and decisions made of the TK
records fetched since then (a Besluit that now says how a vote went is an old node), the
dossiers whose own record was, and both ends of every edge written since then (a new vote,
signature, paper or law). What is touched in another way (a cabinet, a post, the date of a
publication) waits for the nightly run over all.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Callable

from lawgraph.config.constants import (
    COLLECTION_CASES,
    COLLECTION_COMMITMENTS,
    COLLECTION_DECISIONS,
    COLLECTION_DOCUMENTS,
    RAW_KIND_TK_BESLUIT,
    RAW_KIND_TK_DOCUMENT,
    RAW_KIND_TK_DOSSIER,
    RAW_KIND_TK_STEMMING,
    RAW_KIND_TK_TOEZEGGING,
    RAW_KIND_TK_ZAAK,
    SOURCE_TK,
)
from lawgraph.core.models import make_node_key
from lawgraph.core.time import iso_timestamp
from lawgraph.core.tk_records import decision_key
from lawgraph.db.counting import Store
from lawgraph.db.queries import raw as raw_queries
from lawgraph.db.queries.normalize import tk as normalize_tk
from lawgraph.db.queries.semantic import tk as semantic_tk

# The raw records of the Tweede Kamer whose node can change without a new edge, the
# collection of that node and its key.
_NODES_OF_RECORDS: tuple[tuple[str, str, Callable[[str], str]], ...] = (
    (RAW_KIND_TK_TOEZEGGING, COLLECTION_COMMITMENTS, make_node_key),
    (RAW_KIND_TK_DOCUMENT, COLLECTION_DOCUMENTS, make_node_key),
    (RAW_KIND_TK_ZAAK, COLLECTION_CASES, make_node_key),
    (RAW_KIND_TK_BESLUIT, COLLECTION_DECISIONS, decision_key),
)


def edge_moment(since: dt.datetime) -> str:
    """*since* as an edge writes ``created_at`` (``isoformat`` in UTC), so they compare."""
    if since.tzinfo is None:
        since = since.replace(tzinfo=dt.timezone.utc)
    return since.astimezone(dt.timezone.utc).isoformat()


def tk_nodes_fetched_since(store: Store, since: dt.datetime) -> list[str]:
    """The ``_id`` of the nodes made of the TK records fetched at or after *since*, and
    of the decisions its Stemming records voted on."""
    cutoff = iso_timestamp(since)
    ids = []
    for kind, collection, key in _NODES_OF_RECORDS:
        records = raw_queries.ids_stored_since(
            store, source=SOURCE_TK, kind=kind, cutoff_iso=cutoff
        )
        ids += [f"{collection}/{key(str(record))}" for record in records if record]
    votes = [
        str(record)
        for record in raw_queries.ids_stored_since(
            store, source=SOURCE_TK, kind=RAW_KIND_TK_STEMMING, cutoff_iso=cutoff
        )
        if record
    ]
    if votes:
        ids += [
            f"{COLLECTION_DECISIONS}/{row['key']}"
            for row in normalize_tk.decisions_of_vote_records(store, votes)
        ]
    return sorted(set(ids))


def touched_dossiers(
    store: Store, since: dt.datetime, seeds: list[str] | None = None
) -> list[str]:
    """The ``_id`` of the dossiers touched at or after *since*; *seeds* the nodes of the
    records fetched since then when the caller has them (``tk_nodes_fetched_since``)."""
    if seeds is None:
        seeds = tk_nodes_fetched_since(store, since)
    guids = [
        str(record)
        for record in raw_queries.ids_stored_since(
            store,
            source=SOURCE_TK,
            kind=RAW_KIND_TK_DOSSIER,
            cutoff_iso=iso_timestamp(since),
        )
        if record
    ]
    return semantic_tk.touched_dossier_ids(store, seeds, guids, edge_moment(since))


def touched_commitments(
    store: Store, since: dt.datetime, seeds: list[str] | None = None
) -> list[str]:
    """The ``_id`` of the commitments touched at or after *since* (*seeds* as above)."""
    if seeds is None:
        seeds = tk_nodes_fetched_since(store, since)
    return semantic_tk.touched_ids(
        store, COLLECTION_COMMITMENTS, seeds, edge_moment(since)
    )

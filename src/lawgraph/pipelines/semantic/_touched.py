"""What a poll touched in the Tweede Kamer: for the steps that would otherwise read all.

``semantic tk-government`` and ``semantic tk-dossier-outcomes`` read every dossier and
commitment, since what decides them can change without the dossier's own record changing.
With ``--touched-since`` they read only what was touched since then, and come to the same
for it as a run over all: the commitments, documents, cases and decisions made of the TK
records fetched since then (a Besluit that now says how a vote went is an old node), the
dossiers whose own record was, and both ends of every edge written since then (a new vote,
signature, document or law) that the step reads (``GOVERNMENT_EDGES``, ``OUTCOME_EDGES``):
a wave of edges it does not read (the actors of every case, the links between documents)
touches nothing of it. What is touched in another way (a cabinet, a post, the date of a
publication) waits for the nightly run over all.

``semantic tk-dossier-relations`` reads only the replacements then: the cases of the records
fetched since then (a case that now replaces another) and both ends of a ``PART_OF`` edge
written since then (a document that joins a case).

``semantic tk-paper-outcomes`` reads only the papers whose outcome can change: those made of
the records fetched since then or at an end of an edge of ``PAPER_EDGES`` written since then,
every paper of a case among those or of the case such a paper is part of, and the papers of
the decisions among them (the case a decision singles out, the paper it is about).
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
    RELATION_ABOUT,
    RELATION_AUTHORED,
    RELATION_LEGISLATED_IN,
    RELATION_PART_OF,
    RELATION_REVISES,
    RELATION_VOTED,
    SOURCE_TK,
)
from lawgraph.core.models import make_node_key, node_id
from lawgraph.core.time import iso_timestamp
from lawgraph.core.tk_records.decisions import decision_key
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


# The edges whose writing can change what a step derives, by relation, with the collections
# an edge of that relation to does not count for. ``tk-government``: the signature of a
# document (not of a case: ``tk-case-actors``) and a document or case that joins a dossier.
GOVERNMENT_EDGES: dict[str, tuple[str, ...]] = {
    RELATION_AUTHORED: (COLLECTION_CASES,),
    RELATION_PART_OF: (),
}
# ``tk-dossier-outcomes``: a decision about a dossier or its case, a vote on it, the
# publication of its law, and a case that joins a dossier.
OUTCOME_EDGES: dict[str, tuple[str, ...]] = {
    RELATION_ABOUT: (),
    RELATION_VOTED: (),
    RELATION_LEGISLATED_IN: (),
    RELATION_PART_OF: (),
}
# ``tk-dossier-relations`` (replacements): a document that joins a case.
REPLACEMENT_EDGES: dict[str, tuple[str, ...]] = {RELATION_PART_OF: ()}
# ``tk-paper-outcomes``: a document that joins a case, a decision about a paper (a vote of
# the Eerste Kamer), a vote on a decision, and a paper a newer one replaces.
PAPER_EDGES: dict[str, tuple[str, ...]] = {
    RELATION_PART_OF: (),
    RELATION_ABOUT: (),
    RELATION_VOTED: (),
    RELATION_REVISES: (),
}


def edge_moment(since: dt.datetime) -> str:
    """*since* as an edge writes ``created_at`` (``isoformat`` in UTC), so they compare."""
    if since.tzinfo is None:
        since = since.replace(tzinfo=dt.UTC)
    return since.astimezone(dt.UTC).isoformat()


def tk_nodes_fetched_since(store: Store, since: dt.datetime) -> list[str]:
    """The ``id`` of the nodes made of the TK records fetched at or after *since*, and
    of the decisions its Stemming records voted on."""
    cutoff = iso_timestamp(since)
    ids = []
    for kind, collection, key in _NODES_OF_RECORDS:
        records = raw_queries.ids_changed_since(
            store, source=SOURCE_TK, kind=kind, since_iso=cutoff
        )
        ids += [f"{collection}/{key(str(record))}" for record in records if record]
    votes = [
        str(record)
        for record in raw_queries.ids_changed_since(
            store, source=SOURCE_TK, kind=RAW_KIND_TK_STEMMING, since_iso=cutoff
        )
        if record
    ]
    if votes:
        ids += [
            node_id(COLLECTION_DECISIONS, row["key"])
            for row in normalize_tk.decisions_of_vote_records(store, votes)
        ]
    return sorted(set(ids))


def touched_dossiers(
    store: Store,
    since: dt.datetime,
    seeds: list[str] | None = None,
    *,
    edges: dict[str, tuple[str, ...]],
) -> list[str]:
    """The ``id`` of the dossiers touched at or after *since* by a record or by one of the
    *edges* the step reads; *seeds* the nodes of the records fetched since then when the
    caller has them (``tk_nodes_fetched_since``)."""
    if seeds is None:
        seeds = tk_nodes_fetched_since(store, since)
    guids = [
        str(record)
        for record in raw_queries.ids_changed_since(
            store,
            source=SOURCE_TK,
            kind=RAW_KIND_TK_DOSSIER,
            since_iso=iso_timestamp(since),
        )
        if record
    ]
    return semantic_tk.touched_dossier_ids(
        store, seeds, guids, edge_moment(since), edges
    )


def touched_commitments(
    store: Store, since: dt.datetime, seeds: list[str] | None = None
) -> list[str]:
    """The ``id`` of the commitments touched at or after *since* (*seeds* as above)."""
    if seeds is None:
        seeds = tk_nodes_fetched_since(store, since)
    return semantic_tk.touched_ids(
        store, COLLECTION_COMMITMENTS, seeds, edge_moment(since), GOVERNMENT_EDGES
    )


def touched_papers(store: Store, since: dt.datetime) -> list[str]:
    """The ``id`` of the papers whose outcome what was touched at or after *since* can
    change: those touched themselves, every paper of a touched case, and the papers of the
    touched decisions (``semantic_tk.touched_paper_ids``)."""
    seeds, moment = tk_nodes_fetched_since(store, since), edge_moment(since)
    decisions = semantic_tk.touched_ids(
        store, COLLECTION_DECISIONS, seeds, moment, PAPER_EDGES
    )
    cases = semantic_tk.primary_cases(store, decisions)
    return semantic_tk.touched_paper_ids(
        store, sorted({*seeds, *decisions, *cases}), moment, PAPER_EDGES
    )


def touched_cases(store: Store, since: dt.datetime) -> list[str]:
    """The ``id`` of the cases touched at or after *since* for their replacements."""
    return semantic_tk.touched_ids(
        store,
        COLLECTION_CASES,
        tk_nodes_fetched_since(store, since),
        edge_moment(since),
        REPLACEMENT_EDGES,
    )

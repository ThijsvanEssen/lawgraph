"""The derived columns of a node table derived again from ``props``, and which tables need it.

A release that changes how a table derives its columns (``schema.derive_digest``) replaces
its trigger, but rows written before keep what the old one derived. ``pipeline_state``
holds per table (``derive <table>``) the digest its rows were derived by and, while a
series of slices from the start is under way, where it has got to (``through``).
"""

from __future__ import annotations

from typing import Any

from lawgraph.db.counting import Store
from lawgraph.db.queries import state as state_queries
from lawgraph.db.schema import DERIVE_STATE, derive_digest, derived_collections

# Rows written again per statement (a transaction each).
BATCH = 1000


def stale_collections(store: Store) -> list[str]:
    """The tables whose rows were derived by another derivation than this version's."""
    kept = state_queries.states_starting_with(store, DERIVE_STATE)
    return [
        c
        for c in derived_collections()
        if (kept.get(DERIVE_STATE + c) or {}).get("digest") != derive_digest(c)
    ]


def derive_batch(store: Store, collection: str, after: str | None, size: int) -> Any:
    """Write the next *size* rows of *collection* past the id *after* again, which fires
    its trigger (``UPDATE OF props``, the value unchanged): ``{count, last}``, the rows
    written and the id of the last, in the order of the table's ids."""
    past = "WHERE id > %(after)s" if after is not None else ""
    rows = store.execute(
        f"""
        WITH batch AS (
            SELECT id FROM {collection} {past} ORDER BY id LIMIT %(size)s
        ), written AS (
            UPDATE {collection} t SET props = t.props FROM batch
            WHERE t.id = batch.id RETURNING t.id
        )
        SELECT count(*) AS count, max(id) AS last FROM written
        """,
        {"after": after, "size": size},
    )
    return rows[0]


def record_progress(
    store: Store, collection: str, *, after: str | None, last: str | None, done: bool
) -> bool:
    """Keep how far the series of slices that derives *collection* again has got: one that
    starts at the start (*after* None) or where the series ended goes on with it, and when
    it reached the end (*done*) the table holds this version's digest. A slice elsewhere
    leaves the state as it is. Whether the table is derived by this version now."""
    key = DERIVE_STATE + collection
    kept = state_queries.get_state(store, key) or {}
    digest = derive_digest(collection)
    series = kept.get("series") or {}
    continues = after is None or (
        series.get("digest") == digest and series.get("through") == after
    )
    if not continues:
        return kept.get("digest") == digest
    if done:
        state_queries.set_state(store, key, {"digest": digest})
        return True
    series = {"digest": digest, "through": last}
    state_queries.set_state(store, key, {**kept, "series": series})
    return False

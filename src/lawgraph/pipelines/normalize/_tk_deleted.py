"""What the Tweede Kamer deleted leaves the graph.

The Kamer does not drop a record it deletes: the API gives it again with ``Verwijderd`` and
its id, nothing else. Every TK normalizer gathers those ids while it reads its records, with
a ``Deleted`` of its own, and removes in one call what an earlier run made of them.
"""

from __future__ import annotations

from collections.abc import Callable

from lawgraph.config.constants import COLLECTION_EDGES
from lawgraph.core import tk_records
from lawgraph.core.models import make_node_key
from lawgraph.core.tk_records import Payload
from lawgraph.db import Store
from lawgraph.db.queries.normalize import edges as normalize_edges


class Deleted:
    """The records of one kind the Kamer deleted, and what the graph made of them.

    A deleted record names nothing but its id, so what was made of it is found by that id:
    a node whose key *key* makes of it, a node keyed by a label (a dossier number, a
    faction abbreviation: *key* ``None``) whose ``props.external_id(s)`` are that id alone,
    or, when *collection* is the edges, an edge whose ``meta.record_ids`` are.
    """

    def __init__(
        self, collection: str, key: Callable[[str], str] | None = make_node_key
    ) -> None:
        self.collection = collection
        self.key = key
        self.ids: set[str] = set()

    def __call__(self, payload: Payload) -> bool:
        """Whether the Kamer deleted the record *payload*; its id is kept when it did."""
        if not tk_records.is_deleted(payload):
            return False
        if record_id := str(payload.get("Id") or ""):
            self.ids.add(record_id)
        return True

    def remove(self, store: Store) -> int:
        """Remove what was made of the deleted records alone, with every edge at a node that
        goes; how many nodes or edges went."""
        ids = sorted(self.ids)
        if not ids:
            return 0
        if self.collection == COLLECTION_EDGES:
            return normalize_edges.remove_edges_of_records(store, ids)
        if self.key is None:
            return normalize_edges.remove_nodes_of_records(store, self.collection, ids)
        keys = sorted({self.key(record_id) for record_id in ids})
        return normalize_edges.remove_nodes(store, self.collection, keys)

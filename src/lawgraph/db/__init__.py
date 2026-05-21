"""LawGraph database package.

Re-exports ArangoStore and _edge_key from db.store so that all existing
``from lawgraph.db import ArangoStore`` imports continue to work unchanged.
"""

from lawgraph.db.store import ArangoStore, _edge_key

__all__ = ["ArangoStore", "_edge_key"]

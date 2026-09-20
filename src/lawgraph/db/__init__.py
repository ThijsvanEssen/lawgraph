"""LawGraph database package.

Re-exports the public database API so that ``from lawgraph.db import ArangoStore``
(and friends) keep working unchanged.
"""

from lawgraph.db.edges import EdgeWriter, make_edge_doc
from lawgraph.db.nodes import NodeWriter
from lawgraph.db.store import ArangoStore, edge_key

__all__ = ["ArangoStore", "EdgeWriter", "NodeWriter", "edge_key", "make_edge_doc"]

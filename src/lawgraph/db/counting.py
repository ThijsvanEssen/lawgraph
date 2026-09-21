"""Count what a pipeline writes, at the one place every write passes: the store.

``CountingStore`` wraps a store and tallies the created/updated counts the store
already returns from its upserts. A pipeline that holds a ``CountingStore`` gets
every write counted — through ``NodeWriter``, ``EdgeWriter`` or a direct store
call, in the pipeline class or in a helper that only receives ``store`` — without
passing a result object around.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from lawgraph.core.models import Node


@dataclass
class WriteCounts:
    """Nodes and edges a store created, updated or found to be what was written."""

    nodes_created: int = 0
    nodes_updated: int = 0
    nodes_unchanged: int = 0
    edges_created: int = 0
    edges_updated: int = 0
    edges_unchanged: int = 0

    @property
    def created(self) -> int:
        return self.nodes_created + self.edges_created

    @property
    def updated(self) -> int:
        return self.nodes_updated + self.edges_updated

    def describe(self) -> str:
        return (
            f"nodes {self.nodes_created:,} created / {self.nodes_updated:,} updated / "
            f"{self.nodes_unchanged:,} unchanged, "
            f"edges {self.edges_created:,} created / {self.edges_updated:,} updated / "
            f"{self.edges_unchanged:,} unchanged"
        )


class CountingStore:
    """A store that counts its own upserts in ``writes``; everything else passes through."""

    def __init__(self, store: Any) -> None:
        self._store = store
        self.writes = WriteCounts()

    def __getattr__(self, name: str) -> Any:
        return getattr(self._store, name)

    def reset_counts(self) -> None:
        self.writes = WriteCounts()

    def insert_or_update(self, node: Node) -> tuple[Node, bool]:
        stored, created = self._store.insert_or_update(node)
        if created:
            self.writes.nodes_created += 1
        else:
            self.writes.nodes_updated += 1
        return stored, created

    def bulk_insert_or_update_nodes(
        self, collection: str, docs: list[dict[str, Any]]
    ) -> tuple[int, int]:
        created, updated = self._store.bulk_insert_or_update_nodes(collection, docs)
        self.writes.nodes_created += created
        self.writes.nodes_updated += updated
        self.writes.nodes_unchanged += max(0, len(docs) - created - updated)
        return created, updated

    def bulk_insert_or_update_edges(
        self, docs: list[dict[str, Any]]
    ) -> tuple[int, int]:
        created, updated = self._store.bulk_insert_or_update_edges(docs)
        self.writes.edges_created += created
        self.writes.edges_updated += updated
        self.writes.edges_unchanged += max(0, len(docs) - created - updated)
        return created, updated

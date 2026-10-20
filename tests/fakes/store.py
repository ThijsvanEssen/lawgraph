"""One store in memory: ``InMemoryStore`` has the methods of ``GraphStore`` the pipelines
call, with the same signatures (``tests/test_fakes.py`` keeps them so)."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Iterator
from typing import TYPE_CHECKING, Any

from lawgraph.core.models import TYPE_OF_COLLECTION, Node
from lawgraph.core.relations import META_KEYS
from lawgraph.db import raw_key

if TYPE_CHECKING:
    # A fake store is a GraphStore to the type checker, which checks its methods against
    # those of the real store; at run time it is nothing but itself.
    from lawgraph.db import GraphStore

    FakeStoreBase = GraphStore
else:
    FakeStoreBase = object


def raw_record(
    source: str,
    kind: str,
    external_id: str,
    *,
    fetched_at: str = "2026-01-01T00:00:00Z",
    **fields: Any,
) -> dict[str, Any]:
    """A ``raw_sources`` document as ``raw_source_doc`` makes it, fetched at *fetched_at*."""
    return {
        "key": raw_key(source, kind, external_id),
        "source": source,
        "kind": kind,
        "external_id": external_id,
        "fetched_at": fetched_at,
        **fields,
    }


class InMemoryStore(FakeStoreBase):
    """A ``GraphStore`` in memory.

    ``nodes`` (collection -> key -> document), ``edges`` (key -> edge) and ``raw`` (key ->
    raw_sources document) are upserted as the real store does: a node merges its props one
    level deep and unions its labels, an edge merges its ``meta``. Every write of a key that
    exists counts as updated. A record keeps its ``payload_text``: ``with_payloads`` passes it on.
    """

    def __init__(
        self,
        nodes: dict[str, Iterable[dict[str, Any]]] | None = None,
        *,
        edges: Iterable[dict[str, Any]] = (),
        raw: Iterable[dict[str, Any]] = (),
    ) -> None:
        self.nodes: dict[str, dict[str, dict[str, Any]]] = {
            collection: {doc["key"]: doc for doc in docs}
            for collection, docs in (nodes or {}).items()
        }
        self.edges: dict[str, dict[str, Any]] = {edge["key"]: edge for edge in edges}
        self.raw: dict[str, dict[str, Any]] = {doc["key"]: doc for doc in raw}
        # what a pipeline keeps in ``pipeline_state`` (``patch_kept_state``)
        self.kept: dict[str, dict[str, Any]] = {}

    # ── nodes ────────────────────────────────────────────────────────────────

    def bulk_insert_or_update_nodes(
        self, collection: str, docs: list[dict[str, Any]]
    ) -> tuple[int, int]:
        bucket = self.nodes.setdefault(collection, {})
        created = 0
        for doc in docs:
            stored = bucket.get(doc["key"])
            if stored is None:
                created += 1
                bucket[doc["key"]] = dict(doc)
                continue
            labels = [*stored.get("labels", []), *doc.get("labels", [])]
            stored.update(
                {k: v for k, v in doc.items() if k not in ("labels", "props")},
                labels=list(dict.fromkeys(labels)),
                props={**stored.get("props", {}), **doc.get("props", {})},
            )
        return created, len(docs) - created

    def insert_or_update(self, node: Node) -> tuple[Node, bool]:
        created, _ = self.bulk_insert_or_update_nodes(
            node.collection, [node.to_document()]
        )
        stored = self.get_node(node.collection, node.key or "")
        assert stored is not None
        return stored, created == 1

    def get_document(self, collection: str, key: str) -> dict[str, Any] | None:
        return self.nodes.get(collection, {}).get(key)

    def get_node(self, collection: str, key: str) -> Node | None:
        doc = self.get_document(collection, key)
        return Node.from_document(collection, doc) if doc is not None else None

    def ensure_stub_node(
        self, collection: str, key: str, props: dict[str, Any]
    ) -> Node | None:
        if not self.has_node(collection, key):
            stub: dict[str, Any] = {
                "key": key,
                "type": TYPE_OF_COLLECTION[collection].value,
                "labels": [],
            }
            self.nodes.setdefault(collection, {})[key] = {
                **stub,
                "props": {**props, "stub": True},
            }
        return self.get_node(collection, key)

    def has_node(self, collection: str, key: str) -> bool:
        return self.get_document(collection, key) is not None

    def existing_keys(
        self, collection: str, keys: Iterable[str], *, chunk_size: int = 5000
    ) -> set[str]:
        return set(keys) & set(self.nodes.get(collection, {}))

    # ── edges ────────────────────────────────────────────────────────────────

    def bulk_insert_or_update_edges(
        self, docs: list[dict[str, Any]]
    ) -> tuple[int, int]:
        created = 0
        for doc in docs:
            stored = self.edges.get(doc["key"])
            if stored is None:
                created += 1
                self.edges[doc["key"]] = dict(doc)
                continue
            # as the real store: of the stored meta the keys the model of the relation has
            allowed = META_KEYS.get(stored.get("relation", ""), frozenset())
            kept = {k: v for k, v in (stored.get("meta") or {}).items() if k in allowed}
            stored.update(
                {k: doc.get(k) for k in ("confidence", "source", "status")},
                meta={**kept, **(doc.get("meta") or {})},
            )
        return created, len(docs) - created

    # ── raw sources ──────────────────────────────────────────────────────────

    def insert_raw_sources(self, docs: list[dict[str, Any]]) -> None:
        """As the real store: a document fetched again as it was keeps its
        ``changed_at``."""
        moments = ("fetched_at", "changed_at")
        for doc in docs:
            old = self.raw.get(doc["key"]) or {}
            same = {k: v for k, v in old.items() if k not in moments} == {
                k: v for k, v in doc.items() if k not in moments
            }
            changed_at = old.get("changed_at") or old.get("fetched_at")
            self.raw[doc["key"]] = {
                **doc,
                "changed_at": changed_at if old and same else doc.get("fetched_at"),
            }

    def with_payloads(
        self, records: Iterable[dict[str, Any]], *, batch_size: int = 16
    ) -> Iterator[dict[str, Any]]:
        return iter(records)

    def vacuum_analyze(self) -> None:
        """What the phases after retrieve ask of the database when they are done."""

    def analyze_changed(self) -> None:
        """What a run ``--since`` of the phases after retrieve asks of the database."""


def count_calls(store: InMemoryStore, *names: str) -> Counter[str]:
    """How often each of the methods *names* of *store* is called from now on."""
    calls: Counter[str] = Counter()
    for name in names:
        method = getattr(store, name)

        def counted(
            *args: Any, name: str = name, method: Any = method, **kw: Any
        ) -> Any:
            calls[name] += 1
            return method(*args, **kw)

        setattr(store, name, counted)
    return calls


def external_ids(store: InMemoryStore, kind: str | None = None) -> list[str]:
    """The external ids of the raw records *store* holds (of *kind*), in the order stored."""
    return [
        doc["external_id"]
        for doc in store.raw.values()
        if kind is None or doc["kind"] == kind
    ]


# ── pipeline state ───────────────────────────────────────────────────────────


class PipelineStateFake(InMemoryStore):
    """A store as ``pipelines/watermark`` sees it: until when each phase is covered, in
    ``state`` (phase -> moment). ``patch_pipeline_state`` points the state queries at it."""

    def __init__(self) -> None:
        super().__init__()
        self.state: dict[str, str] = {}

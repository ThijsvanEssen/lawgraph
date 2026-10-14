"""The fakes the unit tests share: one store in memory, and the query functions it answers.

``InMemoryStore`` has the methods of ``GraphStore`` the pipelines call, with the same
signatures (``tests/test_fakes.py`` keeps them so). A read of ``db/queries/`` is no store
method: a test patches the function, and the patches here answer it from the store's data.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Iterator
from itertools import islice
from typing import Any

import pytest
import requests

from lawgraph.core.models import TYPE_OF_COLLECTION, Node
from lawgraph.db.queries import raw as raw_queries
from lawgraph.db.queries import state as state_queries
from lawgraph.db.queries.semantic import bwb as semantic_bwb
from lawgraph.db.queries.semantic import edges as semantic_edges
from lawgraph.db.store import raw_key


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
        "_key": raw_key(source, kind, external_id),
        "source": source,
        "kind": kind,
        "external_id": external_id,
        "fetched_at": fetched_at,
        **fields,
    }


class InMemoryStore:
    """A ``GraphStore`` in memory.

    ``nodes`` (collection -> key -> document), ``edges`` (key -> edge) and ``raw`` (key ->
    raw_sources document) are upserted as the real store does: a node merges its props one
    level deep and unions its labels, an edge merges its ``meta``. Every write of a key that
    exists counts as updated. ``insert_raw_sources`` refuses the records whose external id
    is in *refuse*. A record keeps its ``payload_text``: ``with_payloads`` passes it on.
    """

    def __init__(
        self,
        nodes: dict[str, Iterable[dict[str, Any]]] | None = None,
        *,
        edges: Iterable[dict[str, Any]] = (),
        raw: Iterable[dict[str, Any]] = (),
        refuse: Iterable[str] = (),
    ) -> None:
        self.nodes: dict[str, dict[str, dict[str, Any]]] = {
            collection: {doc["_key"]: doc for doc in docs}
            for collection, docs in (nodes or {}).items()
        }
        self.edges: dict[str, dict[str, Any]] = {edge["_key"]: edge for edge in edges}
        self.raw: dict[str, dict[str, Any]] = {doc["_key"]: doc for doc in raw}
        self.refuse = set(refuse)

    # ── nodes ────────────────────────────────────────────────────────────────

    def bulk_insert_or_update_nodes(
        self, collection: str, docs: list[dict[str, Any]]
    ) -> tuple[int, int]:
        bucket = self.nodes.setdefault(collection, {})
        created = 0
        for doc in docs:
            stored = bucket.get(doc["_key"])
            if stored is None:
                created += 1
                bucket[doc["_key"]] = dict(doc)
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
            stub = {
                "_key": key,
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
            stored = self.edges.get(doc["_key"])
            if stored is None:
                created += 1
                self.edges[doc["_key"]] = dict(doc)
                continue
            stored.update(
                {k: doc.get(k) for k in ("confidence", "source", "status")},
                meta={**(stored.get("meta") or {}), **(doc.get("meta") or {})},
            )
        return created, len(docs) - created

    # ── raw sources ──────────────────────────────────────────────────────────

    def insert_raw_sources(
        self, docs: list[dict[str, Any]]
    ) -> list[tuple[dict[str, Any], str]]:
        failures = []
        for doc in docs:
            if doc.get("external_id") in self.refuse:
                failures.append((doc, f"{doc['external_id']} refused"))
            else:
                self.raw[doc["_key"]] = doc
        return failures

    def with_payloads(
        self, records: Iterable[dict[str, Any]], *, batch_size: int = 16
    ) -> Iterator[dict[str, Any]]:
        return iter(records)

    def vacuum_analyze(self) -> None:
        """What the phases after retrieve ask of the database when they are done."""


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


# ── query functions, answered from an InMemoryStore ──────────────────────────


def _records(
    store: InMemoryStore, source: str, kinds: Iterable[str]
) -> list[dict[str, Any]]:
    """The raw records of *source* and *kinds*, in the order of the real queries."""
    return sorted(
        (
            doc
            for doc in store.raw.values()
            if doc["source"] == source and doc["kind"] in kinds
        ),
        key=lambda doc: (doc["kind"], doc["_key"]),
    )


def _since(doc: dict[str, Any], moment: str | None) -> bool:
    return moment is None or doc["fetched_at"] >= moment


def _iter_raw_records(
    store: InMemoryStore,
    *,
    source: str,
    kinds: list[str],
    since_iso: str | None,
    batch_size: int,
    chronological: bool = False,
    after: str | None = None,
    limit: int | None = None,
) -> Iterator[dict[str, Any]]:
    records = [
        doc
        for doc in _records(store, source, kinds)
        if _since(doc, since_iso) and (after is None or doc["_key"] > after)
    ]
    if chronological:
        records.sort(
            key=lambda doc: (
                (doc.get("meta") or {}).get("bwb_id") or "",
                (doc.get("meta") or {}).get("start_date") or "",
                doc["_key"],
            )
        )
    return islice(records, limit)


def _count_raw_records(store: InMemoryStore, source: str, kinds: list[str]) -> int:
    return len(_records(store, source, kinds))


def _fetch_times(
    store: InMemoryStore, *, source: str, kind: str
) -> Iterator[dict[str, Any]]:
    return iter(
        [
            {"id": doc["external_id"], "at": doc["fetched_at"]}
            for doc in _records(store, source, [kind])
        ]
    )


def _ids_stored_since(
    store: InMemoryStore, *, source: str, kind: str, cutoff_iso: str | None
) -> Iterator[str]:
    return iter(
        [
            doc["external_id"]
            for doc in _records(store, source, [kind])
            if _since(doc, cutoff_iso)
        ]
    )


def _ids_waiting_for_retry(
    store: InMemoryStore, *, source: str, kind: str, now_iso: str | None
) -> Iterator[str]:
    def waiting(doc: dict[str, Any]) -> bool:
        retry_after = (doc.get("meta") or {}).get("retry_after")
        return retry_after is not None and (now_iso is None or retry_after > now_iso)

    return iter(
        [doc["external_id"] for doc in _records(store, source, [kind]) if waiting(doc)]
    )


def patch_raw_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    """The reads of ``db/queries/raw.py`` the retrieve and normalize pipelines share,
    answered from the ``raw`` of an ``InMemoryStore`` (the ``raw_reads`` fixture)."""
    monkeypatch.setattr(raw_queries, "iter_raw_records", _iter_raw_records)
    monkeypatch.setattr(raw_queries, "count_raw_records", _count_raw_records)
    monkeypatch.setattr(raw_queries, "fetch_times", _fetch_times)
    monkeypatch.setattr(raw_queries, "ids_stored_since", _ids_stored_since)
    monkeypatch.setattr(raw_queries, "ids_waiting_for_retry", _ids_waiting_for_retry)


def _removed(
    store: InMemoryStore,
    end: str,
    relations: list[str],
    source: str,
    ids: list[str],
    keep: dict[str, set[str]],
) -> int:
    gone = [
        key
        for key, edge in store.edges.items()
        if edge[end] in ids
        and edge.get("relation") in relations
        and edge.get("source") == source
        and key not in keep.get(edge[end], set())
    ]
    for key in gone:
        del store.edges[key]
    return len(gone)


def _remove_edges_from(
    store: InMemoryStore,
    relation: str,
    source: str,
    from_ids: list[str],
    keep: dict[str, set[str]],
    *,
    chunk: int = 5000,
) -> int:
    return _removed(store, "_from", [relation], source, from_ids, keep)


def _remove_edges_to(
    store: InMemoryStore,
    relations: list[str],
    source: str,
    to_ids: list[str],
    keep: dict[str, set[str]],
    *,
    chunk: int = 5000,
) -> int:
    return _removed(store, "_to", relations, source, to_ids, keep)


def patch_edge_removals(monkeypatch: pytest.MonkeyPatch) -> None:
    """``remove_edges_from`` and ``remove_edges_to`` of ``db/queries/semantic/edges.py``, on
    the ``edges`` of an ``InMemoryStore``."""
    monkeypatch.setattr(semantic_edges, "remove_edges_from", _remove_edges_from)
    monkeypatch.setattr(semantic_edges, "remove_edges_to", _remove_edges_to)


_ALIAS_FIELDS = (
    "short_title",
    "aliases",
    "bwb_id",
    "celex",
    "title",
    "citation_title",
    "citation_titles",
)


def _alias_rows(store: InMemoryStore) -> Iterator[dict[str, Any]]:
    instruments = sorted(store.nodes.get("instruments", {}).items())
    return iter(
        [
            {field: doc.get("props", {}).get(field) for field in _ALIAS_FIELDS}
            for _, doc in instruments
            if doc.get("props", {}).get("bwb_id") or doc.get("props", {}).get("celex")
        ]
    )


def patch_alias_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    """``code_alias_rows`` and ``instrument_alias_rows``, from the instruments of an
    ``InMemoryStore``."""
    monkeypatch.setattr(semantic_bwb, "code_alias_rows", _alias_rows)
    monkeypatch.setattr(semantic_bwb, "instrument_alias_rows", _alias_rows)


# ── HTTP ─────────────────────────────────────────────────────────────────────


def http_error(status: int) -> requests.HTTPError:
    """What a client raises for an answer with HTTP *status*, after its retries."""
    response = requests.Response()
    response.status_code = status
    return requests.HTTPError(f"{status}", response=response)


class FakeResponse:
    """What a client reads of a ``requests.Response``: the body as text and as bytes."""

    def __init__(
        self, text: str, content_type: str = "text/xml", url: str = "https://fake"
    ) -> None:
        self.url = url
        self.text = text
        self.content = text.encode("utf-8")
        self.headers = {"Content-Type": content_type}
        self.status_code = 200


# ── pipeline state ───────────────────────────────────────────────────────────


class PipelineStateFake(InMemoryStore):
    """A store as ``pipelines/watermark`` sees it: until when each phase is covered, in
    ``state`` (phase -> moment). ``patch_pipeline_state`` points the state queries at it."""

    def __init__(self) -> None:
        super().__init__()
        self.state: dict[str, str] = {}


def patch_pipeline_state(monkeypatch: pytest.MonkeyPatch) -> None:
    """The queries of ``db/queries/state.py``, answered from a ``PipelineStateFake``."""

    def covered_until(store: PipelineStateFake, phase: str) -> str | None:
        return store.state.get(phase)

    def set_covered_until(store: PipelineStateFake, phase: str, began_iso: str) -> None:
        store.state[phase] = began_iso

    monkeypatch.setattr(state_queries, "covered_until", covered_until)
    monkeypatch.setattr(state_queries, "set_covered_until", set_covered_until)

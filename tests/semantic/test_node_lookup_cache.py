"""SemanticPipelineBase node lookups: cached per run, prefetched in bulk."""

from __future__ import annotations

from collections.abc import Iterable

from lawgraph.core.batching import chunked
from lawgraph.core.models import Node
from lawgraph.pipelines.semantic.base import SemanticPipelineBase
from tests.fakes import FakeStoreBase
from tests.optional import present

ARTICLES = "articles"


class _Store(FakeStoreBase):
    def __init__(self, existing: set[str]) -> None:
        self.existing = existing
        self.get_calls: list[str] = []
        self.bulk_calls: list[set[str]] = []

    def get_node(self, collection: str, key: str) -> Node | None:
        self.get_calls.append(key)
        if key not in self.existing:
            return None
        return Node.skeleton(collection, key, {"text": "large body"})

    def existing_keys(
        self, collection: str, keys: Iterable[str], *, chunk_size: int = 5000
    ) -> set[str]:
        wanted = set(keys)
        self.bulk_calls.append(wanted)
        return wanted & self.existing


class _Pipeline(SemanticPipelineBase):
    def run(self, **kwargs):  # pragma: no cover - not used
        raise NotImplementedError


def test_repeated_lookups_hit_the_database_once_including_misses() -> None:
    store = _Store({"a"})
    pipeline = _Pipeline(store=store)

    for _ in range(5):
        assert pipeline._lookup_node(ARTICLES, "a") is not None
        assert pipeline._lookup_node(ARTICLES, "missing") is None

    # One existence check per distinct key, hits and misses, and never the whole document.
    assert store.bulk_calls == [{"a"}, {"missing"}]
    assert store.get_calls == []


def test_cached_node_is_a_skeleton_without_props() -> None:
    pipeline = _Pipeline(store=_Store({"a"}))

    node = pipeline._lookup_node(ARTICLES, "a")

    assert node is not None and node.node_id == f"{ARTICLES}/a"
    assert node.props == {}  # the large body is not kept in memory


def test_prefetch_resolves_many_keys_with_one_query() -> None:
    store = _Store({"a", "b"})
    pipeline = _Pipeline(store=store)

    pipeline._prefetch_nodes(ARTICLES, {"a", "b", "c"})

    assert len(store.bulk_calls) == 1
    assert pipeline._lookup_node(ARTICLES, "a") is not None
    assert pipeline._lookup_node(ARTICLES, "c") is None
    assert store.get_calls == []  # served from the prefetch


def test_prefetch_skips_keys_already_cached() -> None:
    store = _Store({"a"})
    pipeline = _Pipeline(store=store)
    pipeline._prefetch_nodes(ARTICLES, {"a"})

    pipeline._prefetch_nodes(ARTICLES, {"a", "b"})

    assert store.bulk_calls[1] == {"b"}


def test_remember_node_makes_new_stub_visible() -> None:
    pipeline = _Pipeline(store=_Store(set()))
    assert pipeline._lookup_node(ARTICLES, "stub") is None

    pipeline._remember_node(Node.skeleton(ARTICLES, "stub", {"stub": True}))

    assert pipeline._lookup_node(ARTICLES, "stub") is not None


def test_chunked_splits_without_losing_items() -> None:
    assert list(chunked(range(7), 3)) == [[0, 1, 2], [3, 4, 5], [6]]
    assert list(chunked([], 3)) == []


def test_an_instrument_is_its_bwb_id_first_else_its_celex() -> None:
    both = {"bwb_id": "BWBR0001", "celex": "32016R0679"}
    pipeline = _Pipeline(store=_Store({"bwbr0001", "32016r0679"}))
    assert present(pipeline._resolve_instrument(**both)).key == "bwbr0001"
    only_celex = _Pipeline(store=_Store({"32016r0679"}))
    assert present(only_celex._resolve_instrument(**both)).key == "32016r0679"
    assert _Pipeline(store=_Store(set()))._resolve_instrument(**both) is None


def test_a_tk_hit_on_an_alias_with_both_ids_finds_the_instrument_by_either() -> None:
    from lawgraph.core.citations import CitationHit
    from lawgraph.pipelines.semantic.tk import TKSemanticPipeline

    hit = CitationHit(kind="instrument", bwb_id="BWBR0001", celex="32016R0679")
    only_bwb = TKSemanticPipeline(store=_Store({"bwbr0001"}))
    assert present(only_bwb._resolve_target_node(hit)).key == "bwbr0001"

"""SemanticPipelineBase node lookups: cached per run, prefetched in bulk."""

from __future__ import annotations

from lawgraph.core.batching import chunked
from lawgraph.core.models import Node, NodeType
from lawgraph.pipelines.semantic.base import SemanticPipelineBase

ARTICLES = "articles"


class _Store:
    def __init__(self, existing: set[str]) -> None:
        self.existing = existing
        self.get_calls: list[str] = []
        self.bulk_calls: list[set[str]] = []

    def get_node(self, collection: str, key: str) -> Node | None:
        self.get_calls.append(key)
        if key not in self.existing:
            return None
        return Node(
            collection=collection,
            type=NodeType.ARTICLE,
            key=key,
            props={"text": "large body"},
            _skip_validation=True,
        )

    def existing_keys(self, collection: str, keys) -> set[str]:
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

    assert node is not None and node.arango_id == f"{ARTICLES}/a"
    assert node.props == {}  # the large body is not kept in memory


def test_prefetch_resolves_many_keys_with_one_query() -> None:
    store = _Store({"a", "b"})
    pipeline = _Pipeline(store=store)

    pipeline._prefetch_nodes(ARTICLES, {"a", "b", "c"}, NodeType.ARTICLE)

    assert len(store.bulk_calls) == 1
    assert pipeline._lookup_node(ARTICLES, "a") is not None
    assert pipeline._lookup_node(ARTICLES, "c") is None
    assert store.get_calls == []  # served from the prefetch


def test_prefetch_skips_keys_already_cached() -> None:
    store = _Store({"a"})
    pipeline = _Pipeline(store=store)
    pipeline._prefetch_nodes(ARTICLES, {"a"}, NodeType.ARTICLE)

    pipeline._prefetch_nodes(ARTICLES, {"a", "b"}, NodeType.ARTICLE)

    assert store.bulk_calls[1] == {"b"}


def test_remember_node_makes_new_stub_visible() -> None:
    pipeline = _Pipeline(store=_Store(set()))
    assert pipeline._lookup_node(ARTICLES, "stub") is None

    pipeline._remember_node(
        Node(
            collection=ARTICLES,
            type=NodeType.ARTICLE,
            key="stub",
            props={"stub": True},
            _skip_validation=True,
        )
    )

    assert pipeline._lookup_node(ARTICLES, "stub") is not None


def test_chunked_splits_without_losing_items() -> None:
    assert list(chunked(range(7), 3)) == [[0, 1, 2], [3, 4, 5], [6]]
    assert list(chunked([], 3)) == []

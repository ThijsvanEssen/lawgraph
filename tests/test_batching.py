from __future__ import annotations

from lawgraph.core.batching import chunked, chunked_aligned


def test_chunked_splits_in_order() -> None:
    assert list(chunked(range(5), 2)) == [[0, 1], [2, 3], [4]]


def test_chunked_aligned_never_splits_a_run_of_equal_keys() -> None:
    items = ["a1", "a2", "a3", "b1", "c1", "c2"]

    chunks = list(chunked_aligned(items, 2, key=lambda s: s[0]))

    assert chunks == [["a1", "a2", "a3"], ["b1", "c1", "c2"]]


def test_chunked_aligned_behaves_like_chunked_for_distinct_keys() -> None:
    assert list(chunked_aligned(range(5), 2, key=lambda n: n)) == [
        [0, 1],
        [2, 3],
        [4],
    ]
    assert list(chunked_aligned([], 3, key=lambda n: n)) == []

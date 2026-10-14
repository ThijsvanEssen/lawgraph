"""A semantic pipeline writes its edges, and removes its stale ones, through the
``EdgeWriter``.
"""

from __future__ import annotations

from tests.conventions._scan import SRC


def test_semantic_pipelines_end_their_edges_through_the_edge_writer() -> None:
    """A list, a size check, a flush and two `+=` per pipeline: thirteen copies, of which
    one wrote its edges and forgot to count them. `EdgeWriter.flush_into` counts."""
    semantic = SRC / "pipelines" / "semantic"
    offenders = [
        f"{path.name}: {needle}"
        for path in sorted(semantic.glob("*.py"))
        for needle in ("edge_batch", "bulk_insert_or_update_edges(", "edges.created")
        if needle in path.read_text()
    ]
    assert not offenders


def test_semantic_pipelines_remove_stale_edges_through_the_edge_writer() -> None:
    """Each linker kept its own list of the keys it wrote (`edge_key` again, or `doc["_key"]`)
    beside the writer, in four shapes. The writer remembers what it wrote."""
    semantic = SRC / "pipelines" / "semantic"
    offenders = [
        f"{path.name}: {needle}"
        for path in sorted(semantic.glob("*.py"))
        for needle in ("edge_key", "removals.")
        if needle in path.read_text()
    ]
    assert not offenders

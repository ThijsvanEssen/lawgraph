"""Every edge is made by ``make_edge_doc``, which refuses a relation between collections the
catalogue (``core/relations.py``) does not have: a writer that produces an edge in the wrong
direction fails its own tests, as the catalogue promises.

The store writes the edges ``EdgeWriter`` hands it; no other module calls that write or
builds an edge key, so no edge reaches the database past the check."""

from __future__ import annotations

import re

import pytest

from lawgraph.config.constants import (
    COLLECTION_DECISIONS,
    COLLECTION_DOCUMENTS,
    RELATION_ABOUT,
    RELATION_PART_OF,
)
from lawgraph.core.models import node_id
from lawgraph.core.relations import RELATIONS, allows
from lawgraph.db.edges import make_edge_doc
from tests.asserts import show_items
from tests.paths import SRC
from tests.source_scan import python_files

DB = SRC / "db"
# The one writer of edges, the store that writes them and the store that counts them.
_HOMES = {
    "bulk_insert_or_update_edges": {
        DB / "edges.py",
        DB / "store.py",
        DB / "counting.py",
    },
    "edge_key": {DB / "edges.py"},
}


@pytest.mark.parametrize("name", sorted(_HOMES))
def test_edges_are_written_only_through_make_edge_doc(name: str) -> None:
    called = re.compile(rf"\b{name}\(")
    found = {path for path in python_files() if called.search(path.read_text())}
    assert found <= _HOMES[name], sorted(
        str(path.relative_to(SRC)) for path in found - _HOMES[name]
    )


def test_an_edge_outside_the_catalogue_is_refused() -> None:
    # PART_OF never joins a paper to a law; a relation the catalogue lacks is refused too
    for relation, source, target in (
        (RELATION_PART_OF, "documents/kst-1", "instruments/bwbr0001840"),
        ("CITES", "judgments/a", "articles/b"),
    ):
        with pytest.raises(ValueError, match="relation catalogue"):
            make_edge_doc(source, target, relation)


def test_an_edge_in_the_catalogue_is_made() -> None:
    decision = node_id(COLLECTION_DECISIONS, "ek-1")
    motion = node_id(COLLECTION_DOCUMENTS, "kst-i-37020-m")
    assert make_edge_doc(decision, motion, RELATION_ABOUT)["to_id"] == motion


def test_every_end_of_the_catalogue_is_allowed_and_no_other() -> None:
    ends = {(r.name, a, b) for r in RELATIONS for a, b in r.ends}
    failing = [end for end in ends if not allows(*end)]
    assert not failing, show_items(failing)
    assert not allows(RELATION_ABOUT, "commitments", "cases")

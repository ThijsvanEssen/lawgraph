"""The node collections are declared once (``core.models.COLLECTIONS``): the other tables of
them derive from it, and a node's type is that of its collection."""

from __future__ import annotations

import pytest

from lawgraph.core.models import (
    COLLECTION_OF_TYPE,
    COLLECTIONS,
    STUB_COLLECTIONS,
    TYPE_OF_COLLECTION,
    Node,
    NodeType,
)
from lawgraph.core.relations import CONCEPTS
from lawgraph.db.schema import NODE_COLLECTIONS

# name, type, concept, props schema, stub: in the order of the tables of the schema (the
# order of the ``nodes`` view and ``node_of``).
_PINNED = [
    ("instruments", "instrument", "Instrument", "InstrumentProps", True),
    ("articles", "article", "Article", "ArticleProps", True),
    (
        "instrument_versions",
        "instrument_version",
        "InstrumentVersion",
        "InstrumentVersionProps",
        False,
    ),
    (
        "article_versions",
        "article_version",
        "ArticleVersion",
        "ArticleVersionProps",
        False,
    ),
    ("cases", "case", "Case", "CaseProps", False),
    ("documents", "document", "Document", "DocumentProps", False),
    ("judgments", "judgment", "Judgment", "JudgmentProps", True),
    ("dossiers", "dossier", "Dossier", "DossierProps", False),
    ("activities", "activity", "Activity", "ActivityProps", False),
    ("decisions", "decision", "Decision", "DecisionProps", False),
    ("commitments", "commitment", "Commitment", "CommitmentProps", False),
    ("committees", "committee", "Committee", "CommitteeProps", False),
    ("members", "member", "Member", "MemberProps", False),
    ("factions", "faction", "Faction", "FactionProps", False),
    ("cabinets", "cabinet", "Cabinet", "CabinetProps", False),
    ("ministries", "ministry", "Ministry", "MinistryProps", False),
    ("annexes", "annex", "Annex", "AnnexProps", True),
]


def test_the_collections_are_pinned() -> None:
    assert [
        (s.name, s.node_type.value, s.concept, s.props_schema.__name__, s.stub)
        for s in COLLECTIONS
    ] == _PINNED


def test_every_spec_has_a_schema_and_a_concept() -> None:
    for spec in COLLECTIONS:
        assert spec.concept and spec.props_schema.model_fields, spec.name


def test_the_other_tables_derive_from_the_specs() -> None:
    assert NODE_COLLECTIONS == tuple(row[0] for row in _PINNED)
    assert CONCEPTS == {row[2]: row[0] for row in _PINNED}
    assert STUB_COLLECTIONS == {row[0] for row in _PINNED if row[4]}
    assert {c: t.value for c, t in TYPE_OF_COLLECTION.items()} == {
        row[0]: row[1] for row in _PINNED
    }
    assert set(COLLECTION_OF_TYPE) == set(NodeType)


def test_a_node_has_the_type_of_its_collection() -> None:
    node = Node(collection="judgments", key="k", props={"ecli": "ECLI:NL:HR:2020:1"})
    assert node.type is NodeType.JUDGMENT
    assert node.to_document()["type"] == "judgment"


def test_a_stored_document_reads_back_with_the_type_of_its_collection() -> None:
    for doc in ({"key": "k", "props": {}}, {"key": "k", "type": "x", "props": {}}):
        assert Node.from_document("articles", doc).type is NodeType.ARTICLE
    with pytest.raises(ValueError, match="Unknown node collection"):
        Node.from_document("elsewhere", {"key": "k", "type": "article"})


def test_a_skeleton_has_only_the_props_given_and_is_not_validated() -> None:
    bare = Node.skeleton("articles", "a")
    assert (bare.collection, bare.key, bare.labels, bare.props) == (
        "articles",
        "a",
        [],
        {},
    )
    assert Node.skeleton("articles", "a", {"undeclared": 1}).props == {"undeclared": 1}

"""The helpers of ``core.models`` that build and split a node id."""

from __future__ import annotations

import pytest

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_DECISIONS,
    COLLECTION_JUDGMENTS,
)
from lawgraph.core.models import (
    Node,
    NodeType,
    article_id,
    key_of,
    node_id,
    parse_node_id,
)


def test_node_id_joins_collection_and_key() -> None:
    assert node_id(COLLECTION_JUDGMENTS, "ecli_nl_hr_2020_1") == (
        "judgments/ecli_nl_hr_2020_1"
    )


def test_key_of_is_everything_after_the_first_slash() -> None:
    assert key_of("judgments/ecli_nl_hr_2020_1") == "ecli_nl_hr_2020_1"
    assert key_of("instruments/a/b") == "a/b"
    with pytest.raises(ValueError):
        key_of("no-slash")


def test_key_of_and_parse_node_id_round_trip() -> None:
    built = node_id(COLLECTION_DECISIONS, "d1")
    assert parse_node_id(built) == (COLLECTION_DECISIONS, "d1")
    assert key_of(built) == "d1"


def test_article_id() -> None:
    assert article_id("BWBR0005289", "162") == "articles/bwbr0005289_162"
    assert article_id("BWBR0005289", "6:162") == "articles/bwbr0005289_6_162"


def test_node_node_id_uses_node_id() -> None:
    assert Node(COLLECTION_ARTICLES, NodeType.ARTICLE, key="k").node_id == "articles/k"
    assert Node(COLLECTION_ARTICLES, NodeType.ARTICLE).node_id is None


def test_ref_is_an_unvalidated_skeleton_with_the_type_of_its_collection() -> None:
    ref = Node.ref(COLLECTION_JUDGMENTS, "ecli_nl_hr_2020_1")
    assert ref.collection == COLLECTION_JUDGMENTS
    assert ref.type is NodeType.JUDGMENT
    assert ref.key == "ecli_nl_hr_2020_1"
    assert ref.props == {}
    assert ref.labels == []
    assert ref.node_id == "judgments/ecli_nl_hr_2020_1"

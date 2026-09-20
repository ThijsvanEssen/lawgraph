"""Tests for Node props validation via the typed Pydantic schemas.

These cover the happy-path (valid props pass) and the failure-path (unknown
fields and wrong types raise ValueError at Node construction time).
"""

from __future__ import annotations

import pytest

from lawgraph.core.models import Node, NodeType

# ---------------------------------------------------------------------------
# Happy-path: valid props should construct without error
# ---------------------------------------------------------------------------


def test_instrument_valid_props():
    node = Node(
        collection="instruments",
        type=NodeType.INSTRUMENT,
        props={"bwb_id": "BWBR0001854", "display_name": "Wetboek van Strafrecht"},
    )
    assert node.props["bwb_id"] == "BWBR0001854"


def test_judgment_valid_props():
    node = Node(
        collection="judgments",
        type=NodeType.JUDGMENT,
        props={
            "ecli": "ECLI:NL:HR:2020:1234",
            "display_name": "HR 01-01-2020",
            "stub": False,
        },
    )
    assert node.props["ecli"] == "ECLI:NL:HR:2020:1234"


def test_judgment_accepts_the_rechtspraak_rdf_fields():
    node = Node(
        collection="judgments",
        type=NodeType.JUDGMENT,
        props={
            "ecli": "ECLI:NL:HR:2020:1234",
            "court": "Hoge Raad",
            "case_number": "19/01234",
            "related_eclis": ["ECLI:NL:GHAMS:2019:1"],
        },
    )
    assert node.props["court"] == "Hoge Raad"


def test_publication_valid_props():
    node = Node(
        collection="documents",
        type=NodeType.DOCUMENT,
        props={
            "source": "tk",
            "display_name": "Kamerstuk 36000 nr. 3",
            "kind": "Wetsvoorstel",
        },
    )
    assert node.props["source"] == "tk"


def test_dossier_valid_props():
    node = Node(
        collection="dossiers",
        type=NodeType.DOSSIER,
        props={
            "external_id": "ext-1",
            "number": "36000",
            "closed": False,
            "display_name": "Kamerstukdossier 36000",
        },
    )
    assert node.props["number"] == "36000"


def test_article_valid_props():
    node = Node(
        collection="articles",
        type=NodeType.ARTICLE,
        props={
            "bwb_id": "BWBR0001854",
            "article_number": "91",
            "display_name": "Artikel 91",
        },
    )
    assert node.props["article_number"] == "91"


# ---------------------------------------------------------------------------
# Failure-path: unknown field names must be rejected
# ---------------------------------------------------------------------------


def test_instrument_typo_field_raises():
    """bwbr_id is a common typo for bwb_id — must be caught."""
    with pytest.raises(ValueError, match="bwbr_id"):
        Node(
            collection="instruments",
            type=NodeType.INSTRUMENT,
            props={"bwbr_id": "BWBR0001854", "display_name": "Sr"},
        )


def test_judgment_unknown_field_raises():
    with pytest.raises(ValueError, match="raw_ecli"):
        Node(
            collection="judgments",
            type=NodeType.JUDGMENT,
            props={"raw_ecli": "...", "display_name": "test"},
        )


def test_publication_unknown_field_raises():
    with pytest.raises(ValueError, match="dossier_nr"):
        Node(
            collection="documents",
            type=NodeType.DOCUMENT,
            props={"source": "tk", "display_name": "test", "dossier_nr": "36000"},
        )


def test_article_typo_raises():
    with pytest.raises(ValueError, match="artikel_number"):
        Node(
            collection="articles",
            type=NodeType.ARTICLE,
            props={"bwb_id": "BWBR0001854", "artikel_number": "1"},
        )


# ---------------------------------------------------------------------------
# _skip_validation bypasses schema enforcement
# ---------------------------------------------------------------------------


def test_skip_validation_allows_arbitrary_props():
    node = Node(
        collection="instruments",
        type=NodeType.INSTRUMENT,
        props={"arbitrary_key": "value", "another_undeclared": 42},
        _skip_validation=True,
    )
    assert node.props["arbitrary_key"] == "value"


# ---------------------------------------------------------------------------
# from_document bypasses validation (a stored doc may carry unnamed fields)
# ---------------------------------------------------------------------------


def test_from_document_bypasses_validation():
    doc = {
        "_key": "test",
        "type": "instrument",
        "labels": [],
        "props": {"unnamed_field": "value", "bwb_id": "BWBR0001854"},
    }
    node = Node.from_document("instruments", doc)
    assert node.props["unnamed_field"] == "value"


# ---------------------------------------------------------------------------
# Unknown collections pass through without error (no schema registered)
# ---------------------------------------------------------------------------


def test_unknown_collection_no_schema_passes():
    node = Node(
        collection="some_future_collection",
        type=NodeType.TOPIC,
        props={"anything": "goes"},
    )
    assert node.props["anything"] == "goes"

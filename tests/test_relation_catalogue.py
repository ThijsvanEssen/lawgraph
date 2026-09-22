"""The relation catalogue is complete, consistent and in sync with the docs."""

from __future__ import annotations

import pathlib
import re

import pytest

from lawgraph.config import constants
from lawgraph.core.identifiers import is_bwb_id
from lawgraph.core.relations import (
    BY_NAME,
    CONCEPTS,
    RELATION_NAMES,
    RELATIONS,
    block_of,
    render_tables,
)

# Concepts a relation name must not repeat (the target node already says it).
FORBIDDEN_IN_NAMES = {
    "ARTICLE",
    "INSTRUMENT",
    "DOSSIER",
    "DIRECTIVE",
    "JUDGMENT",
    "COMMITTEE",
    "FACTION",
    "PROCEDURE",
    "CASE",
    "DOCUMENT",
}
DOCS = pathlib.Path(__file__).resolve().parents[1] / "docs" / "data-model.md"


def test_constants_are_exactly_the_catalogue() -> None:
    constants_ = {
        value
        for name, value in vars(constants).items()
        if name.startswith("RELATION_") and isinstance(value, str)
    }
    assert constants_ == RELATION_NAMES


def test_names_are_unique_english_snake_case() -> None:
    names = [r.name for r in RELATIONS]
    assert len(names) == len(set(names))
    for name in names:
        assert re.fullmatch(r"[A-Z]+(_[A-Z]+)*", name), name


def test_names_do_not_repeat_the_target_type() -> None:
    for r in RELATIONS:
        assert not (set(r.name.split("_")) & FORBIDDEN_IN_NAMES), r.name


def test_endpoints_are_known_collections() -> None:
    known = set(CONCEPTS.values())
    for r in RELATIONS:
        assert r.sources and r.targets, r.name
        assert set(r.sources) <= known, r.name
        assert set(r.targets) <= known, r.name


def test_every_node_type_has_one_collection_and_every_collection_one_type() -> None:
    from lawgraph.core.models import COLLECTION_OF_TYPE, TYPE_OF_COLLECTION, NodeType

    assert set(COLLECTION_OF_TYPE) == set(NodeType)
    assert len(TYPE_OF_COLLECTION) == len(NodeType)  # no two types share a collection
    # The catalogue's concepts are the node types in CamelCase.
    for concept, collection in CONCEPTS.items():
        snake = re.sub(r"(?<!^)(?=[A-Z])", "_", concept).lower()
        assert TYPE_OF_COLLECTION[collection].value == snake, concept


def test_only_instruments_and_bills_change_law() -> None:
    changers = {CONCEPTS["Instrument"], CONCEPTS["Document"]}
    for name in ("AMENDS", "INTRODUCES", "REPEALS"):
        assert set(BY_NAME[name].sources) == changers, name
    for name in ("BASED_ON", "IMPLEMENTS"):
        assert BY_NAME[name].sources == (CONCEPTS["Instrument"],), name


def test_generated_docs_are_in_sync() -> None:
    document = DOCS.read_text()
    assert block_of(document) == render_tables(), (
        "docs/data-model.md is out of date: python -m lawgraph.core.relations"
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("BWBR0001840", True),
        ("bwbv0001000", True),  # treaties
        (" BWBR0001854 ", True),
        ("BWBR001840", False),
        ("BWBX0001840", False),
        ("BWBR0001840/7", False),
    ],
)
def test_is_bwb_id_covers_statutes_and_treaties(value: str, expected: bool) -> None:
    assert is_bwb_id(value) is expected

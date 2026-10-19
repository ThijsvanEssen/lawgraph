"""The relation catalogue is complete, consistent and in sync with the docs."""

from __future__ import annotations

import re

import pytest

from lawgraph.config import constants
from lawgraph.config.constants import COLLECTION_NAMES, RELATION_LITERALS
from lawgraph.core.identifiers import is_bwb_id
from lawgraph.core.relations import (
    BY_NAME,
    CONCEPTS,
    RELATION_NAMES,
    RELATIONS,
    block_of,
    render_json,
    render_tables,
)
from tests.paths import ROOT

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
DOCS = ROOT / "docs" / "data-model.md"


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


def test_ends_are_pairs_of_known_collections_each_once() -> None:
    known = set(CONCEPTS.values())
    for r in RELATIONS:
        assert r.ends, r.name
        assert len(set(r.ends)) == len(r.ends), r.name
        assert {c for end in r.ends for c in end} <= known, r.name


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


def test_the_api_types_are_the_catalogue() -> None:
    assert RELATION_LITERALS == tuple(r.name for r in RELATIONS)
    assert COLLECTION_NAMES == tuple(CONCEPTS.values())


def test_the_relations_contract_is_in_sync() -> None:
    assert (ROOT / "tests" / "data" / "relations.json").read_text() == render_json(), (
        "tests/data/relations.json is out of date: python -m lawgraph.core.relations"
    )


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


def test_an_unknown_relation_is_left_out_and_none_kept() -> None:
    from lawgraph.core.relations import without_unknown_relations

    edges: list[dict[str, str | None]] = [
        {"relation": "PART_OF"},
        {"relation": "LATER"},
        {"relation": None},
    ]
    assert without_unknown_relations(edges, lambda e: e["relation"]) == [
        {"relation": "PART_OF"},
        {"relation": None},
    ]

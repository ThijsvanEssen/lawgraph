"""Every props field says what it holds, and the props tables of the docs are those of the
schemas (``core.props_catalogue``)."""

from __future__ import annotations

import inspect

from pydantic import BaseModel

from lawgraph.core import props
from lawgraph.core.models import COLLECTIONS
from lawgraph.core.props_catalogue import block_names, blocks_in, replace_blocks
from tests.paths import ROOT

DOCS = ROOT / "docs" / "data-model.md"


def _schemas() -> list[type[BaseModel]]:
    return [
        value
        for value in vars(props).values()
        if inspect.isclass(value)
        and issubclass(value, BaseModel)
        and value.__module__ == props.__name__
    ]


def test_every_field_has_a_description() -> None:
    missing = [
        f"{schema.__name__}.{name}"
        for schema in _schemas()
        for name, field in schema.model_fields.items()
        if not (field.description or "").strip()
    ]
    assert not missing, f"a docstring under each field: {missing}"


def test_every_collection_has_its_block_once() -> None:
    found = blocks_in(DOCS.read_text())
    assert sorted(found) == sorted(block_names()), found
    assert len(block_names()) == len(COLLECTIONS) + 1


def test_the_docs_hold_the_tables_of_the_schemas() -> None:
    text = DOCS.read_text()
    assert replace_blocks(text) == text, (
        "docs/data-model.md is out of date: python -m lawgraph.core.props_catalogue"
    )

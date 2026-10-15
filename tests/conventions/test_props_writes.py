"""A statement that sets props in SQL (``UPDATE <table> ... SET props = ...``) sets only
props the schema of that table names (``core.props``), so ``docs/data-model.md`` lists
every prop the graph holds. The writers that take their keys at run time check them
(``require_named_props``)."""

from __future__ import annotations

import re

import pytest

from lawgraph.config import constants
from lawgraph.core.models import COLLECTION_SPECS, require_named_props
from tests.source_scan import python_files

_SET_PROPS = re.compile(
    r"UPDATE\s+\{?(?P<table>\w+)\}?\s+\w+\s+SET\s+props\s*=(?P<value>.*?)\n\s*(?:FROM|WHERE)\b",
    re.DOTALL,
)
# a quoted name that is not read (``-> 'key'``): a key of json_build_object or lg_unset
_NAME = re.compile(r"(?<!-> )(?<!->> )'([a-z_]+)'")


def _table(name: str) -> str:
    """A table as the statement names it: literally, or by its ``COLLECTION_*`` constant."""
    value = getattr(constants, name, name)
    return value if isinstance(value, str) else name


def props_set_in(text: str) -> list[tuple[str, set[str]]]:
    """``(table, props)`` of each statement in *text* that sets props in SQL."""
    return [
        (_table(match["table"]), set(_NAME.findall(match["value"])))
        for match in _SET_PROPS.finditer(text)
    ]


def _statements() -> list[tuple[str, str, set[str]]]:
    return [
        (path.name, table, names)
        for path in python_files()
        for table, names in props_set_in(path.read_text())
        if table in COLLECTION_SPECS
    ]


def test_the_scan_finds_the_props_a_statement_sets() -> None:
    sql = """
    UPDATE instruments t
    SET props = lg_unset(
        lg_update(t.props, json_build_object('short_title', r.short_title)),
        ARRAY[CASE WHEN r.x IS NULL THEN 'aliases' END]
    )
    WHERE t.props -> 'short_title' IS NULL
    """
    assert props_set_in(sql) == [("instruments", {"short_title", "aliases"})]
    assert _statements(), "no statement found: the scan no longer matches the writers"


@pytest.mark.parametrize(("module", "table", "names"), _statements())
def test_sql_sets_only_props_the_schema_names(
    module: str, table: str, names: set[str]
) -> None:
    require_named_props(table, names)


def test_a_writer_refuses_a_prop_the_schema_does_not_name() -> None:
    require_named_props("dossiers", ["first_signed", "ministry"])
    with pytest.raises(ValueError, match="no_such_prop"):
        require_named_props("dossiers", ["ministry", "no_such_prop"])

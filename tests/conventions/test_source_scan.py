"""The scanner the convention guards read the source with: which strings it sees."""

from __future__ import annotations

import ast

from tests.source_scan import string_literals

_SOURCE = '''"""The module."""

PLAIN = "SELECT 1"


def query(table, keys):
    """The function."""
    return f"SELECT * FROM {table} WHERE key IN ({', '.join(keys)}) LIMIT {f'{10}'}"


async def answer():
    """The coroutine."""


class Shape:
    """The class."""

    name = "shape"
'''


def test_an_f_string_is_read_whole_with_a_mark_per_field() -> None:
    found = string_literals(ast.parse(_SOURCE))
    assert (8, "SELECT * FROM {} WHERE key IN ({}) LIMIT {}") in found
    # the strings inside a field are literals of their own, a nested f-string too
    assert (8, ", ") in found and (8, "{}") in found
    assert [text for _, text in found if "table" in text] == []


def test_docstrings_are_read_only_when_asked() -> None:
    without = string_literals(ast.parse(_SOURCE))
    assert without == [
        (3, "SELECT 1"),
        (8, ", "),
        (8, "SELECT * FROM {} WHERE key IN ({}) LIMIT {}"),
        (8, "{}"),
        (18, "shape"),
    ]
    docstrings = {
        text for _, text in string_literals(ast.parse(_SOURCE), docstrings=True)
    } - {text for _, text in without}
    assert docstrings == {
        "The module.",
        "The function.",
        "The coroutine.",
        "The class.",
    }

"""Unit tests fake a query function of ``db/queries/``, not the database: no fake store
answers ``query``/``execute`` and no unit test reads query text. What a query itself does
is tested against the test database in ``tests/integration/``.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from tests.paths import TESTS
from tests.source_scan import aql_in


def _unit_test_files() -> list[pathlib.Path]:
    return [
        path
        for path in sorted(TESTS.rglob("test_*.py"))
        # the guards in this package hold queries to test their scans on
        if "integration" not in path.parts
        and "conventions" not in path.parts
        and not path.name.startswith("test_store_")
    ]


def _answers_queries(tree: ast.AST) -> list[int]:
    """Lines where a fake store answers a query: a ``query``/``execute`` method."""
    return [
        item.lineno
        for node in ast.walk(tree)
        if isinstance(node, ast.ClassDef)
        for item in node.body
        if isinstance(item, ast.FunctionDef) and item.name in ("query", "execute")
    ]


def test_the_fake_scan_finds_a_query_method() -> None:
    fake = (
        "class _Store:\n    def query(self, aql, bind_vars=None):\n        return []\n"
    )
    assert _answers_queries(ast.parse(fake)) == [2]
    assert not _answers_queries(ast.parse("def query(text):\n    return text\n"))


@pytest.mark.parametrize(
    "path", _unit_test_files(), ids=lambda p: str(p.relative_to(TESTS))
)
def test_unit_tests_fake_query_functions(path: pathlib.Path) -> None:
    source = path.read_text()
    lines = _answers_queries(ast.parse(source)) + aql_in(source)
    assert not lines, (
        f"{path.relative_to(TESTS)}:{sorted(lines)} fakes the database; patch the function of "
        f"db/queries/ the code calls, and test the query in tests/integration/."
    )

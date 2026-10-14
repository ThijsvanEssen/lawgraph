"""The SQL tests and fallbacks of json values are spelled once, in
``db/queries/_json_sql.py``: a query module calls them, it does not write them out again."""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from lawgraph.db.queries import _json_sql

_QUERIES = Path(__file__).parents[1] / "src" / "lawgraph" / "db" / "queries"
_HELPERS = _QUERIES / "_json_sql.py"
_HELPER_NAMES = [
    name
    for name, value in vars(_json_sql).items()
    if callable(value) and not name.startswith("_")
] + ["slim_sql"]

# what each spelling written out again is: the helper to call instead
_SPELLED_OUT = {
    "is_present / is_absent": re.compile(
        r"coalesce\(json_typeof\([^;]*?\), 'null'\) (?:=|<>) 'null'"
    ),
    "is_present (two-valued)": re.compile(r"json_typeof\([^;]*?\) <> 'null'"),
    "array_or_empty": re.compile(
        r"CASE WHEN json_typeof\((.+?)\) = 'array'\s+THEN \1\s+(?:ELSE '\[\]'|END)"
    ),
    "truthy_or": re.compile(r"CASE WHEN lg_truthy\((.+?)\)\s+THEN \1\s+ELSE"),
}


@pytest.mark.parametrize("helper", sorted(_SPELLED_OUT))
def test_a_query_module_calls_the_helper(helper: str) -> None:
    offenders = [
        f"{path.relative_to(_QUERIES)}:{text[: match.start()].count(chr(10)) + 1}"
        for path in sorted(_QUERIES.rglob("*.py"))
        if path != _HELPERS
        for text in [path.read_text()]
        for match in _SPELLED_OUT[helper].finditer(text)
    ]
    assert not offenders, offenders


def test_a_helper_is_called_in_an_f_string() -> None:
    """``{is_present(...)}`` in a plain string is sent to the database as it is written."""
    called = re.compile(r"\{(%s)\(" % "|".join(_HELPER_NAMES))
    offenders = []
    for path in sorted(_QUERIES.rglob("*.py")):
        tree = ast.parse(path.read_text())
        formatted = {
            id(part)
            for node in ast.walk(tree)
            if isinstance(node, ast.JoinedStr)
            for part in ast.walk(node)
        }
        offenders += [
            f"{path.relative_to(_QUERIES)}:{node.lineno}"
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and id(node) not in formatted
            and called.search(node.value)
        ]
    assert not offenders, offenders

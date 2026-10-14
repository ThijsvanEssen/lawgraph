"""The SQL tests and fallbacks of json values are spelled once, in
``db/queries/_json_sql.py``: a query module calls them, it does not write them out again."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

_QUERIES = Path(__file__).parents[1] / "src" / "lawgraph" / "db" / "queries"
_HELPERS = _QUERIES / "_json_sql.py"

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

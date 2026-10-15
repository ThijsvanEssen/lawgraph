"""A semantic pipeline reads the props it uses, not whole documents."""

from __future__ import annotations

import ast
import re

from tests.paths import SRC
from tests.source_scan import is_sql, string_literals

_SEMANTIC_QUERIES = (
    *sorted((SRC / "db" / "queries" / "semantic").glob("*.py")),
    SRC / "db" / "queries" / "graph_stats.py",
)
# A column of whole props: ``j.props`` or ``props``, not a path into them nor a name given
# to what was picked (``... AS props``).
_WHOLE_PROPS = re.compile(
    r"(?<![\w'])(?<!AS )(\w+\.)?props\b(?!\s*(->|#>|\?|@>))", re.I
)
_SELECT_LIST = re.compile(r"\bSELECT\s+(DISTINCT\s+)?(.*?)\s+FROM\b", re.I | re.S)


def _outside_parentheses(sql: str) -> str:
    """*sql* with what stands between parentheses left out: subqueries, CTE bodies and the
    arguments of functions stay on the server; only the outer select list is sent over."""
    kept, depth = [], 0
    for char in sql:
        depth += char == "("
        if depth == 0:
            kept.append(char)
        depth -= char == ")" and depth > 0
    return "".join(kept)


def whole_props_sent(sql: str) -> bool:
    """Whether a select list of the outer statement of *sql* holds whole props."""
    return any(
        _WHOLE_PROPS.search(match.group(2))
        for match in _SELECT_LIST.finditer(_outside_parentheses(sql))
    )


def test_the_scan_tells_whole_props_from_picked_ones() -> None:
    assert whole_props_sent("SELECT j.key, j.props FROM judgments j")
    assert whole_props_sent("SELECT key, props FROM nodes")
    assert whole_props_sent("SELECT a FROM x UNION ALL SELECT b.props FROM y b")
    assert not whole_props_sent("SELECT j.props -> 'ecli' AS ecli FROM judgments j")
    assert not whole_props_sent(
        "SELECT key FROM (SELECT j.key, j.props FROM judgments j) s"
    )
    assert not whole_props_sent("SELECT {} FROM judgments j")  # slim_sql(...)
    assert not whole_props_sent(
        "SELECT coalesce(lg_keep(d.props), '{}') AS props FROM d"
    )


def test_a_semantic_pipeline_does_not_have_whole_documents_sent_over() -> None:
    """A judgment is its XML, its text and its paragraphs; a loader asks for what it reads.

    ``slim_sql(alias, *fields)`` in ``db/queries/semantic/`` projects the props in the query.
    """
    offenders = []
    for path in _SEMANTIC_QUERIES:
        offenders += [
            f"{path.relative_to(SRC)}:{line}"
            for line, text in string_literals(ast.parse(path.read_text()))
            if is_sql(text) and whole_props_sent(text)
        ]
    assert not offenders, offenders

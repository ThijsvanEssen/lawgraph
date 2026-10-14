"""A semantic pipeline reads the props it uses, not whole documents."""

from __future__ import annotations

import ast
import re

from tests.paths import SRC

_WHOLE_DOCUMENT = re.compile(r"RETURN (doc|art|inst|j|pub)\b(?![._\[])")
_SEMANTIC_QUERIES = (
    *sorted((SRC / "db" / "queries" / "semantic").glob("*.py")),
    SRC / "db" / "queries" / "graph_stats.py",
)
# `semantic tk` scans every text prop of a paper and its API payload: it needs the document.
_READS_WHOLE_DOCUMENTS = {"tk_documents"}


def _exempt_lines(tree: ast.AST) -> set[int]:
    return {
        number
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name in _READS_WHOLE_DOCUMENTS
        for number in range(node.lineno, (node.end_lineno or node.lineno) + 1)
    }


def test_a_semantic_pipeline_does_not_have_whole_documents_sent_over() -> None:
    """A judgment is its XML, its text and its paragraphs; a loader asks for what it reads.

    ``slim_sql(alias, *fields)`` in ``db/queries/semantic/`` projects the props in the query.
    """
    offenders = []
    for path in _SEMANTIC_QUERIES:
        text = path.read_text()
        exempt = _exempt_lines(ast.parse(text))
        offenders += [
            f"{path.relative_to(SRC)}:{number}"
            for number, line in enumerate(text.splitlines(), 1)
            if number not in exempt and _WHOLE_DOCUMENT.search(line)
        ]
    assert not offenders, offenders

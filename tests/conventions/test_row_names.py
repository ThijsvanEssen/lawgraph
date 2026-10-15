"""A row keeps the names of its columns (``db/_rows.py``): ``id``, ``key``, ``from_id`` and
``to_id``, in Python and in the objects a statement builds. A statement names the row of a
table by an alias of a letter, not ``doc`` (a column of ``edges``, ``raw_sources`` and
``pipeline_state``)."""

from __future__ import annotations

import ast
import re

from tests.paths import SRC
from tests.source_scan import python_files, string_literals

_RENAMED = re.compile(r"""["']_(key|id|from|to)["']""")
_DOC_ALIAS = re.compile(r"\b(FROM|JOIN)\s+\S+\s+doc\b|\)\s*doc\b|(?<![\w.])doc\.[\w{*]")


def test_a_row_has_the_names_of_its_columns() -> None:
    found = [
        f"{path.relative_to(SRC)}:{n}"
        for path in python_files()
        for n, line in enumerate(path.read_text().splitlines(), 1)
        if _RENAMED.search(line)
    ]
    assert found == []


def test_no_statement_names_a_row_doc() -> None:
    found = [
        f"{path.relative_to(SRC)}:{n}"
        for path in python_files()
        for n, text in string_literals(ast.parse(path.read_text()))
        if _DOC_ALIAS.search(text)
    ]
    assert found == []

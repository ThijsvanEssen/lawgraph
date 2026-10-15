"""Identifiers are English. Dutch belongs to the sources: the modules that read a
source's own field names are listed in ``_scan.SOURCE_FACING``.
"""

from __future__ import annotations

import ast
import io
import pathlib
import tokenize

import pytest

from tests.paths import SRC
from tests.source_scan import DUTCH_STEMS, SOURCE_KIND_PREFIX, owned_files


def _identifiers(tree: ast.AST) -> set[str]:
    """Every name this module defines: functions, classes, arguments, targets."""
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
        elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
            names.add(node.id)
        elif isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Store):
            names.add(node.attr)
        elif isinstance(node, ast.alias):
            names.add(node.asname or node.name.rsplit(".", 1)[-1])
    return names


@pytest.mark.parametrize("path", owned_files(), ids=lambda p: p.name)
def test_identifiers_have_no_dutch_stems(path: pathlib.Path) -> None:
    tree = ast.parse(path.read_text())
    offenders = {
        name
        for name in _identifiers(tree)
        if not name.startswith(SOURCE_KIND_PREFIX)
        for stem in DUTCH_STEMS
        if stem in name.lower()
    }
    assert not offenders, (
        f"{path.relative_to(SRC)} defines {sorted(offenders)}; the graph and "
        f"the API use the English vocabulary."
    )


def test_module_names_have_no_dutch_stems() -> None:
    offenders = [
        str(path.relative_to(SRC))
        for path in owned_files()
        for stem in DUTCH_STEMS
        if stem in path.stem.lower()
    ]
    assert not offenders, offenders


# A Kamerstuk is a ``document`` in code, as the collection and the URL name it; ``paper``
# is left in API class names, stored props and pipeline names, which change with those. The
# count may only fall.
PAPER_NAMES_MAX = 61


def test_a_kamerstuk_is_a_document_in_code() -> None:
    count = sum(
        1
        for path in owned_files()
        for token in tokenize.generate_tokens(io.StringIO(path.read_text()).readline)
        if token.type == tokenize.NAME and "paper" in token.string.lower()
    )
    assert count <= PAPER_NAMES_MAX, f"{count} names with 'paper'; call it a document"

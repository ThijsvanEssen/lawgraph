"""SQL is not filled in with ``str.replace``: a template is a function of what fills it, so
a misspelled marker cannot leave it unfilled."""

from __future__ import annotations

import ast

from tests.conventions._scan import DB, SRC


def _fills_in_text(node: ast.Call) -> bool:
    """Whether *node* is a ``x.replace(old, ...)`` whose *old* is more than a character or
    two of a value (``'`` to ``''``): a part of a statement. ``os.replace`` moves a file."""
    func = node.func
    if not (isinstance(func, ast.Attribute) and func.attr == "replace" and node.args):
        return False
    if isinstance(func.value, ast.Name) and func.value.id == "os":
        return False
    old = node.args[0]
    return not (
        isinstance(old, ast.Constant)
        and isinstance(old.value, str)
        and len(old.value) <= 2
    )


def test_no_sql_is_filled_in_with_replace() -> None:
    offenders = [
        f"{path.relative_to(SRC)}:{node.lineno}"
        for path in sorted(DB.rglob("*.py"))
        if path.name != "store.py"  # it redacts the secrets of a URL, no SQL
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.Call) and _fills_in_text(node)
    ]
    assert not offenders, offenders

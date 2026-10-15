"""A route module's private names stay in it: what another module needs of a route (the
totals of the lists, the warm-up) is public."""

from __future__ import annotations

import ast

from tests.paths import SRC
from tests.source_scan import python_files

ROUTES = "lawgraph.api.routes"


def _private_uses(tree: ast.AST) -> list[str]:
    modules: set[str] = set()
    found = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module == ROUTES:
            modules |= {alias.asname or alias.name for alias in node.names}
        elif isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
            ROUTES
        ):
            found += [a.name for a in node.names if a.name.startswith("_")]
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.Attribute)
            and isinstance(node.value, ast.Name)
            and node.value.id in modules
            and node.attr.startswith("_")
        ):
            found.append(f"{node.value.id}.{node.attr}")
    return found


def test_no_module_reads_a_private_name_of_a_route() -> None:
    offenders = {
        str(path.relative_to(SRC)): uses
        for path in python_files()
        if (uses := _private_uses(ast.parse(path.read_text())))
    }
    assert not offenders, f"make it public: {offenders}"

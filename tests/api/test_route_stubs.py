"""The route unit tests open no database: every loader a route module imports from
``lawgraph.db.queries`` (a ``load_*``) is stubbed by the conftest, in every route module,
also in one added later."""

from __future__ import annotations

import ast
import importlib
import pkgutil

import lawgraph.api.routes as routes
from tests.paths import SRC


def _imported_loaders(source: str) -> list[str]:
    """The ``load_*`` names *source* imports from ``lawgraph.db.queries``."""
    return [
        alias.asname or alias.name
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.ImportFrom)
        and (node.module or "").startswith("lawgraph.db.queries")
        for alias in node.names
        if alias.name.startswith("load_")
    ]


def _route_loaders() -> list[tuple[str, str]]:
    """``(module, name)`` of every query loader a route module imports."""
    return [
        (info.name, name)
        for info in pkgutil.iter_modules(routes.__path__)
        for name in _imported_loaders(
            (SRC / "api" / "routes" / f"{info.name}.py").read_text()
        )
    ]


def test_the_scan_reads_a_loader_import() -> None:
    assert _imported_loaders(
        "from lawgraph.db.queries.dossiers import enrich_dossier_docs, load_dossier_names\n"
        "from lawgraph.db.queries import load_x as y\n"
        "from lawgraph.core.text import load_words\n"
    ) == ["load_dossier_names", "y"]
    assert ("activities", "load_dossier_names") in _route_loaders()


def test_every_route_loader_is_stubbed() -> None:
    real = [
        f"{module}.{name}"
        for module, name in _route_loaders()
        if getattr(
            getattr(importlib.import_module(f"{routes.__name__}.{module}"), name),
            "__module__",
            "",
        ).startswith("lawgraph.")
    ]
    assert not real, f"these read the store in a unit test: {real}"

"""What the route unit tests put in place of the database: a store that knows no node,
the loaders' answers, and ``stub_route`` for the queries of one route module."""

from __future__ import annotations

import importlib
import pkgutil
from collections.abc import Callable
from types import ModuleType
from typing import Any

import pytest

import lawgraph.api.routes as routes


class MockStore:
    """Knows no node; every query a route under test reads is stubbed."""

    def get_document(self, collection: str, key: str) -> Any:
        return None


# The names of the dossiers the routes put next to a bare number, as ``load_dossier_names``
# reads them: one bill.
DOSSIER_NAMES = {
    "36000": {
        "number": "36000",
        "short_title": "Wet beter voorbeeld",
        "title": "Wijziging van de Wet X (Wet beter voorbeeld)",
    },
}


def _dossier_names(store: Any) -> dict[str, dict[str, str]]:
    return DOSSIER_NAMES


# Each loader a route module imports from ``lawgraph.db.queries``, by name, and what stands
# in for it (``test_route_stubs.py`` checks that every one has a stand-in).
LOADERS: dict[str, Callable[[Any], Any]] = {"load_dossier_names": _dossier_names}


def route_modules() -> list[ModuleType]:
    return [
        importlib.import_module(f"{routes.__name__}.{info.name}")
        for info in pkgutil.iter_modules(routes.__path__)
    ]


def stub_route(monkeypatch: pytest.MonkeyPatch, module: str, **queries: Any) -> None:
    """Stub the *queries* of the route module *module*: a function stands in for the
    query, any other value is what the query returns."""
    target = importlib.import_module(f"{routes.__name__}.{module}")
    for name, value in queries.items():
        monkeypatch.setattr(
            target,
            name,
            value if callable(value) else (lambda *args, _v=value, **kwargs: _v),
        )

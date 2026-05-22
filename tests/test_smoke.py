import importlib

import pytest


@pytest.mark.parametrize(
    "module",
    [
        "lawgraph",
        "lawgraph.api.app",
        "lawgraph.api.schemas",
        "lawgraph.config.constants",
        "lawgraph.config.settings",
        "lawgraph.core.models",
        "lawgraph.core.time",
        "lawgraph.db.store",
        "lawgraph.pipelines.base",
        "lawgraph.pipelines.factory",
        "lawgraph.sources.registry",
    ],
)
def test_public_module_imports_without_error(module):
    """Each public module must be importable without raising."""
    importlib.import_module(module)

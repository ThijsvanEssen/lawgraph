from __future__ import annotations

import pytest

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store


@pytest.fixture(autouse=True)
def stub_store_override():
    app.dependency_overrides[get_store] = lambda: None
    yield
    app.dependency_overrides.pop(get_store, None)

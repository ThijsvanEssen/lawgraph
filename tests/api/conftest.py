from __future__ import annotations

from collections.abc import Generator

import pytest

from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store


@pytest.fixture(autouse=True)
def stub_store_override() -> Generator[None, None, None]:
    app.dependency_overrides[get_store] = lambda: None
    yield
    app.dependency_overrides.pop(get_store, None)

"""The life of the API process: at the end the search terms are written and the pools of the
stores closed, each once."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from lawgraph.api import app as app_module
from lawgraph.api import search_terms


def test_the_api_writes_its_search_terms_and_closes_its_stores_when_it_stops(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    monkeypatch.setattr(app_module, "API_WARM_UP", False)
    monkeypatch.setattr(app_module, "close_stores", lambda: calls.append("close"))
    monkeypatch.setattr(search_terms, "flush", lambda: calls.append("flush"))
    with TestClient(app_module.app):
        assert calls == []
    assert calls == ["flush", "close"]

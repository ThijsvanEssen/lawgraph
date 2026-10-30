"""GET /api/instruments/aliases: the one table of abbreviations, and the codes with books."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.routes import instruments
from tests.asserts import assert_status


def test_the_abbreviations_and_the_codes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        instruments,
        "load_code_aliases",
        lambda store: {"Sr": "BWBR0001854", "AVG": "32016r0679", "awb": "BWBR0005537"},
    )
    response = TestClient(app).get("/api/instruments/aliases")
    assert_status(response, 200)
    body = response.json()
    assert body["codes"] == [
        {"abbreviation": "AVG", "law_id": "32016R0679"},
        {"abbreviation": "awb", "law_id": "BWBR0005537"},
        {"abbreviation": "Sr", "law_id": "BWBR0001854"},
    ]
    assert body["families"]["BW"]["7"] == "BWBR0005290"
    assert body["names"]["BW"] == ["Burgerlijk Wetboek"]

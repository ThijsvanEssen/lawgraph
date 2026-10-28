"""Every answer says where its time went: ``Server-Timing`` for the client, and the same in
the line of the log."""

from __future__ import annotations

import re

import pytest
from fastapi.testclient import TestClient

from lawgraph.api.app import app
from lawgraph.api.middleware import server_timing
from lawgraph.api.routes import cabinets
from lawgraph.db import request_timing
from tests.asserts import assert_status


def test_an_answer_has_server_timing_and_a_line_with_cache_and_worker(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    def asks_the_cache(store):
        request_timing.add_db(0.25)
        request_timing.miss(0.2)
        return []

    monkeypatch.setattr(cabinets, "get_cabinets", asks_the_cache)
    with caplog.at_level("INFO"):
        response = TestClient(app).get("/api/cabinets")

    assert_status(response, 200)
    header = response.headers["server-timing"]
    assert re.fullmatch(
        r"total;dur=[\d.]+, db;dur=250\.0, cache;desc=miss;dur=200\.0", header
    ), header
    line = next(m for m in caplog.messages if "/api/cabinets" in m)
    assert "cache=miss db=250.0ms worker=" in line


def test_a_request_the_cache_held_is_a_hit_and_one_without_it_has_no_cache_metric() -> (
    None
):
    held = request_timing.RequestTiming(hits=2)
    assert (
        server_timing(held, 12.0)
        == "total;dur=12.0, db;dur=0.0, cache;desc=hit;dur=0.0"
    )
    assert server_timing(request_timing.RequestTiming(), 3.0) == (
        "total;dur=3.0, db;dur=0.0"
    )


def test_one_answer_not_kept_makes_the_request_a_miss() -> None:
    timing = request_timing.RequestTiming(hits=3, misses=1)
    assert timing.cache == "miss"

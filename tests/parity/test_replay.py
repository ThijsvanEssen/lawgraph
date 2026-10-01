"""The latency protocol of replay: warm-up, the median of the runs in turn, and a reference
that answers with an error stops the measurement."""

from __future__ import annotations

from typing import Any

import pytest

from tests.parity.catalogue import Request
from tests.parity.replay import ReferenceFailed, _over, _timed


class _Api:
    """Answers with the given times (ms) and status, one per fetch, and records the order
    of the fetches in *log*."""

    def __init__(
        self, name: str, times: list[float], log: list[str], status: int = 200
    ):
        self.name, self.times, self.log, self.status = name, list(times), log, status

    def fetch(self, request: Request) -> dict[str, Any]:
        self.log.append(self.name)
        return {"status": self.status, "ms": self.times.pop(0)}


def test_the_median_of_the_runs_after_a_warm_up_in_turn() -> None:
    log: list[str] = []
    new = _Api("new", [900, 10, 30, 20], log)
    reference = _Api("ref", [800, 5, 7, 6], log)
    assert _timed(new, reference, Request("/api/x")) == (20, 6)  # type: ignore[arg-type]
    assert log == ["new", "ref"] * 4  # in turn, the slow first round not counted


def test_an_error_of_the_reference_stops_the_measurement() -> None:
    log: list[str] = []
    new = _Api("new", [1] * 4, log)
    reference = _Api("ref", [1] * 4, log, status=500)
    with pytest.raises(ReferenceFailed):
        _timed(new, reference, Request("/api/search", (("q", "wet"),)))  # type: ignore[arg-type]


def test_the_norm_is_ten_percent_or_five_ms() -> None:
    assert not _over(14.9, 10.0)  # within 5 ms
    assert _over(15.1, 10.0)
    assert not _over(110.0, 100.0)  # within 10 %
    assert _over(110.1, 100.0)

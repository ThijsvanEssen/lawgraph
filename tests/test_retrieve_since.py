"""What each windowed retrieve passes its pipeline: the moment of ``--since`` in the form its
source reads, and nothing in full mode."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from lawgraph.core.models import PipelineResult
from lawgraph.pipelines import retrieve_commands
from lawgraph.sources.registry import find

SINCE = "2024-09-20T10:30:00+00:00"
MOMENT = dt.datetime(2024, 9, 20, 10, 30, tzinfo=dt.timezone.utc)
DAY = dt.date(2024, 9, 20)


class _Recorder:
    """A pipeline that records the method it was run with and its arguments."""

    calls: list[tuple[str, dict[str, Any]]]

    def __init__(self, *args: object, **kwargs: object) -> None:
        pass

    def __getattr__(self, method: str) -> Any:
        def run(**kwargs: Any) -> PipelineResult:
            _Recorder.calls.append((method, kwargs))
            return PipelineResult()

        return run


@pytest.fixture
def recorded(monkeypatch) -> list[tuple[str, dict[str, Any]]]:
    _Recorder.calls = []
    monkeypatch.setattr(retrieve_commands, "GraphStore", lambda: object())
    monkeypatch.setattr(
        retrieve_commands.gap_queries, "holds_label", lambda *args: True
    )
    for name in dir(retrieve_commands):
        if name.endswith("RetrievePipeline"):
            monkeypatch.setattr(retrieve_commands, name, _Recorder)
    return _Recorder.calls


def _run(name: str, *argv: str) -> None:
    pipeline = find("retrieve", name)
    assert pipeline is not None
    pipeline.command(list(argv))


@pytest.mark.parametrize(
    ("name", "incremental", "full"),
    [
        (
            "echr",
            (
                "run",
                {"respondent": "NLD", "since_date": "2024-09-20", "max_records": 10000},
            ),
            ("run_full", {"respondent": "NLD"}),
        ),
        (
            "eurlex-nim",
            ("run", {"country_code": "NLD", "since": "2024-09-20"}),
            ("run", {"country_code": "NLD", "since": None}),
        ),
        (
            "eerstekamer",
            ("run", {"since": "2024-09-20", "limit": None}),
            ("run", {"since": None, "limit": None}),
        ),
        ("eerstekamer-votes", ("run", {"since": DAY}), ("run", {"since": None})),
        ("eerstekamer-agenda", ("run", {"since": DAY}), ("run", {"since": None})),
        ("eerstekamer-bills", ("run", {"since": DAY}), ("run", {"since": None})),
        ("staatscourant", ("run", {"since": "2024-09-20"}), ("run_full", {})),
        ("tk-document-links", ("run", {"since": MOMENT}), ("run", {"since": None})),
        ("tk-case-actors", ("run", {"since": MOMENT}), ("run", {"since": None})),
        (
            "tk",
            ("run", {"since": MOMENT, "limit": 0, "replacing": False}),
            (
                "run",
                {
                    "since": dt.datetime(1995, 1, 1, tzinfo=dt.timezone.utc),
                    "limit": 0,
                    "replacing": False,
                },
            ),
        ),
    ],
)
def test_each_source_gets_the_since_it_reads(
    recorded, name: str, incremental: tuple, full: tuple
) -> None:
    _run(name, "--mode", "incremental", "--since", SINCE)
    _run(name, "--mode", "full", "--since", SINCE)
    assert recorded == [incremental, full]

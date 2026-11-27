"""The last run of each part of the warm-up (``/api/health`` ``warm_up``)."""

from __future__ import annotations

from lawgraph.api import warm


def _fail() -> None:
    raise RuntimeError("down")


def test_each_part_keeps_its_last_run_the_newest_first() -> None:
    assert warm._run("first", lambda: None)
    assert not warm._run("second", _fail)
    runs = warm.last_runs()
    assert {run["part"]: run["outcome"] for run in runs} == {
        "first": "done",
        "second": "failed",
    }
    assert runs[0]["began"] >= runs[1]["began"]
    assert [run["part"] for run in runs if run["seconds"] is None] == []


def test_a_part_that_reaches_its_time_says_so() -> None:
    def cut() -> None:
        assert list(warm._for_a_while([1, 2, 3], 0.0, "items")) == []

    assert warm._run("timed", cut)
    assert warm.last_runs()[0]["outcome"] == "stopped: its time"
    assert list(warm._for_a_while([1], 0.0, "outside a run")) == []


def test_forget_clears_the_runs() -> None:
    warm._run("first", lambda: None)
    warm.forget()
    assert warm.last_runs() == []

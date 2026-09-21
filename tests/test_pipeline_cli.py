"""A command returns what it did; ``execute`` decides how it ended; ``__main__`` exits."""

from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

import pytest

from lawgraph import __main__ as entry
from lawgraph.core.models import PipelineResult
from lawgraph.pipelines import command as command_module
from lawgraph.pipelines.command import pipeline_command
from lawgraph.pipelines.execution import Outcome, State, combined, execute, skipped

SRC = Path(__file__).resolve().parents[1] / "src" / "lawgraph"


# ── execute ──────────────────────────────────────────────────────────────────


def test_a_command_that_went_well_ends_ok_with_its_result() -> None:
    outcome = execute("normalize x", lambda argv: PipelineResult(created=1), [])
    assert (outcome.label, outcome.state) == ("normalize x", State.OK)
    assert outcome.result.created == 1


def test_a_result_with_errors_ends_failed() -> None:
    outcome = execute("normalize x", lambda argv: PipelineResult(errors=["boom"]), [])
    assert outcome.state is State.FAILED and outcome.result.errors == ["boom"]


def test_a_command_that_raises_ends_failed_and_the_caller_goes_on() -> None:
    def command(argv: list[str]) -> PipelineResult:
        raise RuntimeError("database unreachable")

    outcome = execute("normalize x", command, [])
    assert outcome.state is State.FAILED
    assert outcome.result.errors == ["RuntimeError: database unreachable"]


def test_ctrl_c_and_a_wrong_command_line_are_not_swallowed() -> None:
    def interrupted(argv: list[str]) -> PipelineResult:
        raise KeyboardInterrupt

    def misread(argv: list[str]) -> PipelineResult:
        raise SystemExit(2)  # argparse

    with pytest.raises(KeyboardInterrupt):
        execute("x", interrupted, [])
    with pytest.raises(SystemExit):
        execute("x", misread, [])


def test_a_parent_adds_up_its_steps_and_names_the_one_that_failed() -> None:
    outcomes = [
        Outcome("normalize a", State.OK, PipelineResult(created=2, skipped=1)),
        Outcome("normalize b", State.FAILED, PipelineResult(created=1, errors=["x"])),
        skipped("normalize c", "LAWGRAPH_NORMALIZE_SKIP_C"),
    ]
    total = combined(outcomes)
    assert (total.created, total.skipped) == (3, 1)
    assert total.errors == ["normalize b failed"]  # its own errors were logged under it


# ── the exit code ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("result", "code"),
    [(PipelineResult(created=1), None), (PipelineResult(errors=["boom"]), 1)],
)
def test_only_the_entry_point_turns_an_outcome_into_an_exit_code(
    monkeypatch, result: PipelineResult, code: int | None
) -> None:
    monkeypatch.setitem(entry._COMMANDS, "check", lambda argv: result)
    if code is None:
        entry.main(["check"])
        return
    with pytest.raises(SystemExit) as exit_info:
        entry.main(["check"])
    assert exit_info.value.code == code


def test_nothing_but_the_entry_points_ends_the_process_or_sets_up_logging() -> None:
    """A command that exits cannot be a step of another command; one that sets up logging
    decides what its caller logs."""
    entry_points = {
        SRC / "__main__.py",
        SRC / "api" / "app.py",
        SRC / "core" / "logging.py",
    }
    offenders = [
        f"{path.relative_to(SRC)}: {match.group(0)}"
        for path in SRC.rglob("*.py")
        if path not in entry_points
        for match in re.finditer(r"sys\.exit\(|setup_logging\(\)", path.read_text())
    ]
    assert not offenders


# ── a command made from a pipeline ───────────────────────────────────────────


class _RecordingPipeline:
    calls: list[dict] = []

    def __init__(self, store: object) -> None:
        pass

    def run(self, **kwargs: object) -> PipelineResult:
        self.calls.append(kwargs)
        return PipelineResult(created=len(self.calls))


def test_since_is_parsed_and_passed_only_when_the_command_accepts_it(
    monkeypatch,
) -> None:
    monkeypatch.setattr(command_module, "ArangoStore", lambda: object())
    _RecordingPipeline.calls = []

    first = pipeline_command(_RecordingPipeline, description="", with_since=True)(
        ["--since", "2024-01-01"]
    )
    pipeline_command(_RecordingPipeline, description="")([])

    assert first.created == 1  # the command hands back what the pipeline returned
    assert _RecordingPipeline.calls == [
        {"since": dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)},
        {},
    ]


def test_command_without_since_rejects_the_option(monkeypatch) -> None:
    monkeypatch.setattr(command_module, "ArangoStore", lambda: object())
    with pytest.raises(SystemExit) as exit_info:
        pipeline_command(_RecordingPipeline, description="")(["--since", "7d"])
    assert exit_info.value.code == 2

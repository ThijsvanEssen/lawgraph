"""Every pipeline command ends the same way: exit code 1 when it raised or reported errors."""

from __future__ import annotations

import datetime as dt

import pytest

from lawgraph.core.models import PipelineResult
from lawgraph.pipelines import factory
from lawgraph.pipelines.factory import make_pipeline_cli, run_command, run_step


def test_run_step_returns_normally_on_success() -> None:
    run_step("step", lambda: PipelineResult(created=1))


def test_run_step_exits_1_when_the_result_has_errors() -> None:
    with pytest.raises(SystemExit) as exit_info:
        run_step("step", lambda: PipelineResult(errors=["boom"]))
    assert exit_info.value.code == 1


def test_run_step_exits_1_when_the_step_raises() -> None:
    def run() -> PipelineResult:
        raise RuntimeError("database unreachable")

    with pytest.raises(SystemExit) as exit_info:
        run_step("step", run)
    assert exit_info.value.code == 1


def test_run_command_reports_failure_instead_of_exiting() -> None:
    def failing(argv: list[str]) -> None:
        raise SystemExit(1)

    assert run_command("ok", lambda argv: None, []) is True
    assert run_command("failing", failing, []) is False


class _RecordingPipeline:
    calls: list[dict] = []

    def __init__(self, store: object) -> None:
        pass

    def run(self, **kwargs: object) -> PipelineResult:
        self.calls.append(kwargs)
        return PipelineResult()


def test_since_is_parsed_and_passed_only_when_the_command_accepts_it(
    monkeypatch,
) -> None:
    monkeypatch.setattr(factory, "ArangoStore", lambda: object())
    _RecordingPipeline.calls = []

    make_pipeline_cli(_RecordingPipeline, description="", with_since=True)(
        ["--since", "2024-01-01"]
    )
    make_pipeline_cli(_RecordingPipeline, description="")([])

    assert _RecordingPipeline.calls == [
        {"since": dt.datetime(2024, 1, 1, tzinfo=dt.timezone.utc)},
        {},
    ]


def test_command_without_since_rejects_the_option(monkeypatch) -> None:
    monkeypatch.setattr(factory, "ArangoStore", lambda: object())
    with pytest.raises(SystemExit) as exit_info:
        make_pipeline_cli(_RecordingPipeline, description="")(["--since", "7d"])
    assert exit_info.value.code == 2

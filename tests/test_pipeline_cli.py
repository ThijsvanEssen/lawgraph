"""A command returns what it did; ``run_command`` decides how it ended; ``__main__`` exits."""

from __future__ import annotations

import datetime as dt

import pytest

from lawgraph import __main__ as entry
from lawgraph.core.logging import describe
from lawgraph.core.models import PipelineResult
from lawgraph.db.raw import StoreUnavailable
from lawgraph.db.schema import SchemaOutdated
from lawgraph.db.store import DatabaseUnavailable
from lawgraph.pipelines import command as command_module
from lawgraph.pipelines.command import (
    Outcome,
    PipelineCommand,
    State,
    combined_result,
    run_command,
)
from lawgraph.pipelines.retrieve.base import SourceDown
from lawgraph.pipelines.watermark import NothingOnRecord
from tests.asserts import show_items
from tests.optional import present

# ── run_command ──────────────────────────────────────────────────────────────────


def test_a_command_that_went_well_ends_ok_with_its_result() -> None:
    outcome = run_command("normalize x", lambda argv: PipelineResult(created=1), [])
    assert (outcome.label, outcome.state) == ("normalize x", State.OK)
    assert outcome.result.created == 1


def test_a_result_with_errors_ends_failed() -> None:
    outcome = run_command(
        "normalize x", lambda argv: PipelineResult(errors=["boom"]), []
    )
    assert outcome.state is State.FAILED and outcome.result.errors == ["boom"]


def test_a_command_that_raises_ends_failed_and_the_caller_goes_on() -> None:
    def command(argv: list[str]) -> PipelineResult:
        raise RuntimeError("database unreachable")

    outcome = run_command("normalize x", command, [])
    assert outcome.state is State.FAILED
    assert outcome.result.errors == ["RuntimeError: database unreachable"]


def test_a_command_that_raises_is_logged_once_with_its_traceback(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def command(argv: list[str]) -> PipelineResult:
        counts: dict[str, int] = {}
        return PipelineResult(created=counts["x"])

    with caplog.at_level("DEBUG"):
        outcome = run_command("normalize x", command, [])
    failed = [record for record in caplog.records if record.exc_info]
    assert [(record.levelname, present(record.exc_info)[0]) for record in failed] == [
        ("ERROR", KeyError)
    ]
    assert outcome.result.errors == ["KeyError: 'x'"]


def test_ctrl_c_and_a_wrong_command_line_are_not_swallowed() -> None:
    def interrupted(argv: list[str]) -> PipelineResult:
        raise KeyboardInterrupt

    def misread(argv: list[str]) -> PipelineResult:
        raise SystemExit(2)  # argparse

    with pytest.raises(KeyboardInterrupt):
        run_command("x", interrupted, [])
    with pytest.raises(SystemExit):
        run_command("x", misread, [])


def test_a_parent_adds_up_its_steps_and_names_the_one_that_failed() -> None:
    outcomes = [
        Outcome("normalize a", State.OK, PipelineResult(created=2, skipped=1)),
        Outcome("normalize b", State.FAILED, PipelineResult(created=1, errors=["x"])),
        Outcome("normalize c", State.SKIPPED),
    ]
    total = combined_result(outcomes)
    assert (total.created, total.skipped) == (3, 1)
    # the first reason of the step goes up with its name: runs.log and the alert say why
    assert total.errors == ["normalize b failed: x"]


def test_a_parent_names_the_first_reason_and_how_many_more() -> None:
    failed = Outcome(
        "semantic tk", State.FAILED, PipelineResult(errors=["a", "b", "c"])
    )
    bare = Outcome("semantic ek", State.FAILED)
    assert combined_result([failed, bare]).errors == [
        "semantic tk failed: a (and 2 more)",
        "semantic ek failed",
    ]


@pytest.mark.parametrize(
    "known",
    [
        DatabaseUnavailable(
            "Cannot connect to PostgreSQL at localhost:5432 (db=x): refused"
        ),
        SchemaOutdated("the tables are not those of the schema: run `lawgraph check`"),
        StoreUnavailable("12 raw records could not be written: timeout"),
        SourceDown("tk: 10 requests in a row failed; the source seems to be down."),
        NothingOnRecord("No complete `retrieve all` is on record"),
    ],
    ids=lambda exc: type(exc).__name__,
)
def test_a_known_failure_is_one_line_without_a_traceback(
    known: Exception, caplog: pytest.LogCaptureFixture
) -> None:
    """Its message says what to do; the traceback is there at DEBUG for whoever asks."""

    def command(argv: list[str]) -> PipelineResult:
        raise known

    with caplog.at_level("DEBUG"):
        outcome = run_command("normalize x", command, [])
    errors = [r for r in caplog.records if r.levelname == "ERROR"]
    assert [(bool(r.exc_info), r.getMessage().split(": ", 1)[1]) for r in errors] == [
        (False, describe(known))
    ]
    assert [r.levelname for r in caplog.records if r.exc_info] == ["DEBUG"]
    assert outcome.state is State.FAILED and outcome.result.errors == [describe(known)]


@pytest.mark.parametrize(
    ("result", "reason"),
    [
        (PipelineResult(errors=["boom", "bang"]), "boom; bang"),
        (PipelineResult(unavailable=["HUDOC: HTTP 403"]), "HUDOC: HTTP 403"),
        (PipelineResult(created=2), "2 created"),
    ],
)
def test_an_outcome_says_why_in_one_line(result: PipelineResult, reason: str) -> None:
    outcome = run_command("check", lambda argv: result, [])
    assert outcome.reason == reason


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


def test_the_entry_point_writes_why_for_the_scheduled_scripts(
    monkeypatch, tmp_path
) -> None:
    """``LAWGRAPH_OUTCOME_FILE``: the reason of the outcome, one line, for runs.log and the
    alert (scripts/_run.sh); the full text is in the log."""
    written = tmp_path / "outcome"
    monkeypatch.setattr(entry, "OUTCOME_FILE", str(written))
    errors = ["ProgrammingError: no column x\nLINE 1: …"]
    monkeypatch.setitem(
        entry._COMMANDS, "check", lambda argv: PipelineResult(errors=errors)
    )
    with pytest.raises(SystemExit):
        entry.main(["check"])
    assert written.read_text(encoding="utf-8") == (
        "ProgrammingError: no column x LINE 1: …\n"
    )
    # a long one is cut at a word, well past what a line of runs.log used to keep (200)
    errors[:] = ["SourceDown: tk: " + "word " * 200]
    with pytest.raises(SystemExit):
        entry.main(["check"])
    said = written.read_text(encoding="utf-8").rstrip("\n")
    assert 280 <= len(said) <= entry.REASON_CHARS and said.endswith("word …")


@pytest.mark.parametrize(
    ("argv", "said"),
    [
        (["retreive", "bwb"], "unknown command 'retreive'; did you mean 'retrieve'?"),
        (["chek"], "unknown command 'chek'; did you mean 'check'?"),
        (["zzz"], "unknown command 'zzz'"),
        (
            ["retrieve", "bwbb"],
            "unknown pipeline 'bwbb' of retrieve; did you mean 'bwb'?",
        ),
        (["normalize"], "normalize needs a pipeline or all"),
    ],
)
def test_an_unknown_command_is_named_above_the_usage(
    argv: list[str], said: str, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as exit_info:
        entry.main(argv)
    assert exit_info.value.code == 2
    err = capsys.readouterr().err
    assert err.splitlines()[0] == f"lawgraph: {said}"
    assert "Usage: lawgraph" in err


# ── a command made from a pipeline ───────────────────────────────────────────


class _Dated:
    calls: list[dict] = []

    def __init__(self, store: object) -> None:
        pass

    def run(self, *, since: dt.datetime | None = None) -> PipelineResult:
        self.calls.append({"since": since})
        return PipelineResult(created=1)


class _Undated:
    """A pipeline whose run takes no window: its calls are kept with those of ``_Dated``."""

    def __init__(self, store: object) -> None:
        pass

    def run(self) -> PipelineResult:
        _Dated.calls.append({})
        return PipelineResult()


def test_a_command_has_since_when_the_run_of_its_pipeline_takes_it(monkeypatch) -> None:
    """It was said three times (`with_since`, `semantic_accepts_since`, the signature) and
    a step that missed one ran in full without a word, or died on an unknown option."""
    monkeypatch.setattr(command_module, "GraphStore", lambda: object())
    _Dated.calls = []
    dated, undated = PipelineCommand(_Dated, ""), PipelineCommand(_Undated, "")

    assert dated.accepts_since and not undated.accepts_since
    assert dated(["--since", "2024-01-01"]).created == 1
    undated([])
    assert _Dated.calls == [
        {"since": dt.datetime(2024, 1, 1, tzinfo=dt.UTC)},
        {},
    ]
    with pytest.raises(SystemExit) as exit_info:
        undated(["--since", "7d"])
    assert exit_info.value.code == 2


def test_every_registered_pipeline_runs_on_since_or_on_nothing() -> None:
    """Or on ``touched_since``: a step that otherwise reads all, which a poll narrows."""
    import inspect

    from lawgraph.sources.registry import PIPELINES

    commands = [
        pipeline.command
        for phase in ("normalize", "semantic")
        for pipeline in PIPELINES[phase]
        if isinstance(pipeline.command, PipelineCommand)
    ]
    assert len(commands) > 25
    for command in commands:
        parameters = set(inspect.signature(command.pipeline_cls.run).parameters)
        name = command.pipeline_cls.__name__
        assert parameters - {"self"} in ({"since"}, {"touched_since"}, set()), name
    failing = [p for p in PIPELINES["normalize"] if not p.command.accepts_since]
    assert not failing, show_items(failing)


def test_a_result_says_what_was_left_as_it_was() -> None:
    """A second run over the same records is mostly that; without it the line said
    "nothing to do" for a step that looked 40,000 documents up."""
    assert PipelineResult(unchanged=41_200, updated=3).summary() == (
        "3 updated, 41,200 unchanged"
    )
    total = combined_result([Outcome("a", State.OK, PipelineResult(unchanged=2))] * 2)
    assert total.unchanged == 4


def test_a_pipeline_command_takes_a_window_in_hours() -> None:
    """The option itself, as `normalize <source> --since 2h` parses it."""
    import argparse
    import datetime as dt

    from lawgraph.pipelines.command import add_since_argument

    parser = argparse.ArgumentParser()
    add_since_argument(parser, last=True)
    since = parser.parse_args(["--since", "90m"]).since
    assert isinstance(since, dt.datetime)
    ago = dt.datetime.now(dt.UTC) - since
    assert abs(ago - dt.timedelta(minutes=90)) < dt.timedelta(seconds=5)
    assert parser.parse_args(["--since", "last"]).since == "last"

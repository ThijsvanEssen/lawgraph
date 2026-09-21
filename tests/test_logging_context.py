"""Every log line says which step it belongs to; steps say what they do and how long."""

from __future__ import annotations

import io
import logging
import threading

import pytest

from lawgraph.core import logging as lg
from lawgraph.core.models import PipelineResult
from lawgraph.core.time import format_duration
from lawgraph.pipelines import execution
from lawgraph.pipelines.execution import State, execute
from lawgraph.pipelines.orchestration import Step, run_phase
from lawgraph.sources.registry import SOURCES, describe


@pytest.fixture
def lines():
    """The formatted output of a handler with the same filter and format as the CLI."""
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.addFilter(lg._StepFilter())
    handler.setFormatter(logging.Formatter(lg.LOG_FORMAT))
    root = logging.getLogger()
    previous_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    yield lambda: stream.getvalue().splitlines()
    root.removeHandler(handler)
    root.setLevel(previous_level)


# ── the step on every line ───────────────────────────────────────────────────


def test_a_line_carries_the_step_and_a_short_logger_name(lines) -> None:
    with lg.log_step("retrieve staatscourant"):
        logging.getLogger("lawgraph.clients.base").info("HTTP 429 from somewhere")
    assert (
        lines()
        == [
            line
            for line in lines()
            if "[INFO] [retrieve staatscourant] clients.base: HTTP 429 from somewhere"
            in line
        ]
        and len(lines()) == 1
    )


def test_a_line_outside_a_step_has_no_empty_brackets(lines) -> None:
    logging.getLogger("lawgraph.core.thing").info("hello")
    assert "[INFO] core.thing: hello" in lines()[0]
    assert "[]" not in lines()[0]


def test_steps_nest_and_the_outer_one_comes_back() -> None:
    with lg.log_step("bootstrap"):
        with lg.log_step("retrieve tk"):
            assert lg.current_step() == "retrieve tk"
        assert lg.current_step() == "bootstrap"
    assert lg.current_step() == ""


def test_threads_keep_their_own_step() -> None:
    seen: dict[str, str] = {}
    barrier = threading.Barrier(2)

    def work(label: str) -> None:
        with lg.log_step(label):
            barrier.wait()  # both threads are inside their step at the same time
            seen[label] = lg.current_step()

    threads = [threading.Thread(target=work, args=(n,)) for n in ("a", "b")]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert seen == {"a": "a", "b": "b"}


def test_json_lines_have_the_step() -> None:
    import json

    record = logging.LogRecord("lawgraph.x", logging.INFO, "f", 1, "msg", None, None)
    with lg.log_step("normalize bwb"):
        lg._StepFilter().filter(record)
    entry = json.loads(lg._JsonFormatter().format(record))
    assert entry["step"] == "normalize bwb" and entry["message"] == "msg"


# ── what a step says about itself ────────────────────────────────────────────


def test_a_step_says_what_it_does_with_which_options_and_how_long(
    lines, monkeypatch
) -> None:
    monkeypatch.setattr(execution.time, "monotonic", iter([0.0, 252.0]).__next__)
    seen: list[str] = []

    def command(argv: list[str]) -> PipelineResult:
        seen.append(lg.current_step())
        return PipelineResult(created=5)

    outcome = execute(
        "retrieve staatscourant",
        command,
        ["--mode", "incremental", "--since", "2024-09-20"],
        description="Ministerial regulations from the Staatscourant.",
    )
    assert outcome.state is State.OK and seen == ["retrieve staatscourant"]
    start, end = lines()  # one line to start and one to end, whoever runs the step
    assert "[retrieve staatscourant]" in start
    assert "Starting: Ministerial regulations from the Staatscourant." in start
    assert "(--mode incremental --since 2024-09-20)" in start
    assert "Done in 4m12s: 5 created." in end


def test_a_failing_step_says_how_long_it_ran_and_why(lines, monkeypatch) -> None:
    monkeypatch.setattr(execution.time, "monotonic", iter([0.0, 65.0, 65.0]).__next__)

    def fail(argv: list[str]) -> PipelineResult:
        raise RuntimeError("no route to host")

    assert execute("normalize x", fail, []).state is State.FAILED
    assert "Failed after 1m05s: RuntimeError: no route to host" in lines()[-1]


def test_every_error_of_a_result_is_a_line(lines) -> None:
    execute("normalize x", lambda argv: PipelineResult(errors=["a", "b"]), [])
    assert [line.split("Error: ")[1] for line in lines() if "Error: " in line] == [
        "a",
        "b",
    ]


@pytest.mark.parametrize(
    ("seconds", "text"),
    [(0, "0s"), (12, "12s"), (59.6, "1m00s"), (252, "4m12s"), (3720, "1h02m")],
)
def test_format_duration(seconds, text) -> None:
    assert format_duration(seconds) == text


def test_a_step_is_called_what_one_types_everywhere(lines) -> None:
    """One name: in the log context, in the table of the phase, in the error of the parent."""
    labels: list[str] = []

    def command(argv: list[str]) -> PipelineResult:
        labels.append(lg.current_step())
        return PipelineResult()

    steps = [
        Step("normalize", "tk_dossiers", command, []),
        Step("normalize", "bwb", command, []),
    ]
    outcomes = run_phase(steps)
    assert labels == ["normalize tk-dossiers", "normalize bwb"]
    assert [o.label for o in outcomes] == labels
    table = [line for line in lines() if line.rstrip().endswith(" ok")]
    assert [line.split()[-4:-2] for line in table] == [
        label.split() for label in labels
    ]


# ── the descriptions ─────────────────────────────────────────────────────────


@pytest.mark.parametrize("source", SOURCES, ids=lambda s: s.id)
def test_every_command_of_every_source_is_described(source) -> None:
    for phase in ("retrieve", "normalize", "semantic"):
        if getattr(source, f"{phase}_main") is not None:
            assert source.descriptions.get(phase), f"{phase} {source.id}"


def test_describe_accepts_the_cli_spelling() -> None:
    assert describe("normalize", "tk-dossiers") == describe("normalize", "tk_dossiers")
    assert "Kamerstukken" in describe("retrieve", "eerstekamer")
    assert describe("retrieve", "nonexistent") == ""
    assert describe("semantic", "tk-content") == ""


def test_the_sources_command_lists_every_source_and_marks_manual_ones(capsys) -> None:
    from lawgraph.__main__ import main

    main(["sources"])
    out = capsys.readouterr().out
    for source in SOURCES:
        assert source.id.replace("_", "-") in out
    tk_content = next(b for b in out.split("\n\n") if b.startswith("tk-content"))
    assert "[manual: not in retrieve all]" in tk_content
    staatscourant = next(b for b in out.split("\n\n") if b.startswith("staatscourant"))
    assert "manual" not in staatscourant

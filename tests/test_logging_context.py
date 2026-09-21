"""Every log line says which step it belongs to; steps say what they do and how long."""

from __future__ import annotations

import io
import logging
import threading

import pytest

from lawgraph.core import logging as lg
from lawgraph.core.models import PipelineResult
from lawgraph.core.time import format_duration
from lawgraph.pipelines import command as command_module
from lawgraph.pipelines.command import State, run_command
from lawgraph.pipelines.orchestration import run_pipelines
from lawgraph.sources.registry import PHASES, PIPELINES, Pipeline


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
    monkeypatch.setattr(command_module.time, "monotonic", iter([0.0, 252.0]).__next__)
    seen: list[str] = []

    def command(argv: list[str]) -> PipelineResult:
        seen.append(lg.current_step())
        return PipelineResult(created=5)

    outcome = run_command(
        "retrieve staatscourant",
        command,
        ["--mode", "incremental", "--since", "2024-09-20"],
        description="Ministerial regulations from the Staatscourant.",
    )
    assert outcome.state is State.OK and seen == ["retrieve staatscourant"]
    start, end = lines()  # one line to start and one to end, whoever runs the step
    assert "[retrieve staatscourant]" in start
    assert start.endswith(
        "Starting: Ministerial regulations from the Staatscourant "
        "(--mode incremental --since 2024-09-20)."
    )
    assert "Done in 4m12s: 5 created." in end


def test_a_failing_step_says_how_long_it_ran_and_why(lines, monkeypatch) -> None:
    monkeypatch.setattr(
        command_module.time, "monotonic", iter([0.0, 65.0, 65.0]).__next__
    )

    def fail(argv: list[str]) -> PipelineResult:
        raise RuntimeError("no route to host")

    assert run_command("normalize x", fail, []).state is State.FAILED
    assert "Failed after 1m05s: RuntimeError: no route to host" in lines()[-1]


def test_every_error_of_a_result_is_a_line(lines) -> None:
    run_command("normalize x", lambda argv: PipelineResult(errors=["a", "b"]), [])
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

    pipelines = [
        Pipeline("normalize", "tk", "dossiers", command, ""),
        Pipeline("normalize", "bwb", None, command, ""),
    ]
    outcomes = run_pipelines(pipelines, lambda pipeline: [])
    assert labels == ["normalize tk-dossiers", "normalize bwb"]
    assert [o.label for o in outcomes] == labels
    table = [line for line in lines() if line.rstrip().endswith(" ok")]
    assert [line.split()[-4:-2] for line in table] == [
        label.split() for label in labels
    ]


# ── the descriptions ─────────────────────────────────────────────────────────


ALL_PIPELINES = [pipeline for phase in PHASES for pipeline in PIPELINES[phase]]


@pytest.mark.parametrize("pipeline", ALL_PIPELINES, ids=lambda p: p.address)
def test_every_pipeline_says_what_it_does(pipeline: Pipeline) -> None:
    assert len(pipeline.description) > 10 and pipeline.description.endswith(".")


def test_the_sources_command_lists_every_pipeline_under_its_source(capsys) -> None:
    from lawgraph.__main__ import main

    main(["sources"])
    blocks = {b.split()[0]: b for b in capsys.readouterr().out.split("\n\n")[1:]}
    for pipeline in ALL_PIPELINES:
        assert pipeline.address in blocks[pipeline.source]
    content = next(
        line for line in blocks["tk"].splitlines() if "retrieve tk-content" in line
    )
    assert "[manual: not in retrieve all]" in content
    assert "manual" not in blocks["staatscourant"]
    assert "semantic rechtspraak-citations" in blocks["rechtspraak"]


def test_the_start_line_ends_with_one_full_stop(lines) -> None:
    run_command(
        "normalize tk", lambda argv: PipelineResult(), [], description="Cases as nodes."
    )
    assert lines()[0].endswith("Starting: Cases as nodes.")

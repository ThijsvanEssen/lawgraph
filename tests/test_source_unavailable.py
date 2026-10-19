"""A source that refuses us (HTTP 401/403, a challenge page) is unavailable: its step is
left out with a warning and the others go on; any other failure still fails the step."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import pytest
import requests

from lawgraph import __main__ as entry
from lawgraph.clients.base import ATTEMPTS
from lawgraph.clients.echr import EchrClient
from lawgraph.commands import expand_graph
from lawgraph.config import settings
from lawgraph.core.models import PipelineResult
from lawgraph.pipelines.command import (
    EXIT_UNAVAILABLE,
    HandWritten,
    Outcome,
    State,
    combined_result,
    run_command,
)
from lawgraph.pipelines.orchestration import run_pipelines
from lawgraph.pipelines.retrieve.echr import ECHRRetrievePipeline
from lawgraph.sources.registry import Pipeline
from tests.fakes import InMemoryStore, ScriptedSession, answer, http_error


def _challenge() -> requests.HTTPError:
    """What Cloudflare answers a client it does not let through."""
    response = answer("<html>Just a moment...</html>", status=503)
    response.headers["cf-mitigated"] = "challenge"
    return requests.HTTPError("503", response=response)


def _echr(error: Exception) -> PipelineResult:
    """A run of ``retrieve echr`` whose every request ends in *error*, after the retries
    of the client."""
    client = EchrClient(session=ScriptedSession(*[error] * ATTEMPTS))
    return ECHRRetrievePipeline(store=InMemoryStore(), client=client).run(
        respondent="NLD"
    )


@pytest.mark.parametrize("error", [http_error(403), http_error(401), _challenge()])
@pytest.mark.usefixtures("slept")
def test_a_source_that_refuses_us_is_unavailable_not_failed(error: Exception) -> None:
    result = _echr(error)
    assert result.errors == []
    assert len(result.unavailable) == 1 and "unavailable" in result.unavailable[0]


@pytest.mark.parametrize("error", [http_error(400), http_error(500)])
@pytest.mark.usefixtures("slept")
def test_any_other_failure_of_the_source_still_fails_the_step(error: Exception) -> None:
    result = _echr(error)
    assert result.errors and result.unavailable == []


def test_an_unavailable_source_ends_its_step_unavailable_with_a_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def command(argv: list[str]) -> PipelineResult:
        return PipelineResult(unavailable=["HUDOC: HTTP 403"])

    with caplog.at_level("INFO"):
        outcome = run_command("retrieve echr", command, [])
    assert outcome.state is State.UNAVAILABLE
    assert [r.levelname for r in caplog.records if "HTTP 403" in r.getMessage()] == [
        "WARNING"
    ]


def _step(
    name: str, result: PipelineResult, ran: list[str], after: tuple[str, ...] = ()
) -> Pipeline:
    def command(argv: list[str] | None = None) -> PipelineResult:
        ran.append(name)
        return result

    return Pipeline("retrieve", name, None, HandWritten(command), "", None, name, after)


def _no_argv(pipeline: Pipeline) -> list[str]:
    return []


def test_retrieve_all_goes_on_without_an_unavailable_source() -> None:
    """Its readers are left out; the phase is not failed, and says what was unavailable."""
    ran: list[str] = []
    steps = [
        _step("echr", PipelineResult(unavailable=["HUDOC: HTTP 403"]), ran),
        _step("rechtspraak", PipelineResult(created=3), ran),
        _step("echr-texts", PipelineResult(), ran, after=("echr",)),
    ]
    outcomes = run_pipelines(steps, _no_argv, jobs=3)
    assert [(o.label, o.state) for o in outcomes] == [
        ("retrieve echr", State.UNAVAILABLE),
        ("retrieve rechtspraak", State.OK),
        ("retrieve echr-texts", State.SKIPPED),
    ]
    assert sorted(ran) == ["echr", "rechtspraak"]
    total = combined_result(outcomes)
    assert total.errors == [] and total.created == 3
    assert total.unavailable == ["retrieve echr: HUDOC: HTTP 403"]
    # the parent of the phase ends unavailable too: the alert goes on
    assert run_command("retrieve all", lambda argv: total, []).state is (
        State.UNAVAILABLE
    )


def test_expand_graph_is_not_failed_by_an_unavailable_source(monkeypatch) -> None:
    records = iter([0, 5, 5, 5])
    monkeypatch.setattr(expand_graph, "GraphStore", lambda: object())
    monkeypatch.setattr(expand_graph, "_count_records", lambda store: next(records))
    gone = PipelineResult(unavailable=["retrieve echr: HUDOC: HTTP 403"])

    def run(label: str, command: Callable[..., Any], argv: list[str]) -> Outcome:
        if label == "retrieve all":
            return Outcome(label, State.UNAVAILABLE, gone)
        return Outcome(label, State.OK)

    monkeypatch.setattr(expand_graph, "run_command", run)
    total = combined_result(expand_graph._expand(max_iterations=3, final_pass=False))
    assert total.errors == []
    assert total.unavailable == ["retrieve all: retrieve echr: HUDOC: HTTP 403"] * 2


@pytest.mark.parametrize(
    ("result", "code"),
    [
        (PipelineResult(unavailable=["HUDOC: HTTP 403"]), EXIT_UNAVAILABLE),
        (PipelineResult(unavailable=["x"], errors=["boom"]), 1),
    ],
)
def test_the_entry_point_tells_unavailable_from_failed(
    monkeypatch, result: PipelineResult, code: int
) -> None:
    monkeypatch.setitem(entry._COMMANDS, "check", lambda argv: result)
    with pytest.raises(SystemExit) as exit_info:
        entry.main(["check"])
    assert exit_info.value.code == code


# ── a source that is off ─────────────────────────────────────────────────────


def _off_step(phase: str, source: str, ran: list[str]) -> Pipeline:
    def command(argv: list[str] | None = None) -> PipelineResult:
        ran.append(f"{phase} {source}")
        return PipelineResult()

    return Pipeline(phase, source, None, HandWritten(command), "", None, source)  # type: ignore[arg-type]


def test_a_source_that_is_off_is_asked_nothing_and_leaves_no_hole(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """No step, so no warning and nothing that keeps ``--since last`` back; what reads its
    stored records still runs."""
    monkeypatch.setattr(settings, "SOURCES_OFF", frozenset({"echr"}))
    ran: list[str] = []
    steps = [
        _off_step("retrieve", "echr", ran),
        _off_step("retrieve", "rechtspraak", ran),
        _off_step("normalize", "echr", ran),
    ]
    with caplog.at_level("INFO"):
        outcomes = run_pipelines(steps, _no_argv)
    assert ran == ["retrieve rechtspraak", "normalize echr"]
    assert all(outcome.state is State.OK for outcome in outcomes)
    assert not [r for r in caplog.records if r.levelname == "WARNING"]


def test_a_source_that_is_off_must_be_one(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LAWGRAPH_SOURCES_OFF", "echr, hudoc")
    with pytest.raises(ValueError, match="hudoc"):
        settings._sources("LAWGRAPH_SOURCES_OFF")


def test_check_notes_a_source_that_is_off_and_finds_no_problem_in_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from lawgraph.commands import check

    monkeypatch.setattr(settings, "SOURCES_OFF", frozenset({"echr"}))
    report = check.Report()
    check._check_raw({}, report)
    assert not [p for p in report.problems if p.startswith("raw echr/")]
    assert "echr: off (LAWGRAPH_SOURCES_OFF), its records not checked" in report.notes

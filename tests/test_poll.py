"""``lawgraph poll``: one source over a window back, each step with the same ``--since``."""

from __future__ import annotations

import datetime as dt

import pytest

from lawgraph.commands import poll
from lawgraph.core.feed import FEED_TIERS
from lawgraph.core.models import PipelineResult
from lawgraph.pipelines import retrieve_commands
from lawgraph.pipelines.command import Outcome, State
from lawgraph.pipelines.retrieve.rechtspraak import resolve_courts


def _ran(
    monkeypatch, argv: list[str]
) -> tuple[list[tuple[str, list[str]]], PipelineResult]:
    ran: list[tuple[str, list[str]]] = []

    def run_pipelines(pipelines, argv_of, **_):
        for pipeline in pipelines:
            ran.append((pipeline.address, argv_of(pipeline)))
        return [Outcome(address, State.OK) for address, _ in ran]

    monkeypatch.setattr(poll, "run_pipelines", run_pipelines)
    return ran, poll.main(argv)


@pytest.mark.parametrize("name", list(poll.POLLS))
def test_every_step_of_a_poll_is_a_pipeline_of_the_registry(name) -> None:
    steps = poll.chain(name)
    phases = [pipeline.phase for pipeline, _ in steps]
    assert phases == sorted(phases, key=["retrieve", "normalize", "semantic"].index)
    assert phases[0] == "retrieve"


def test_a_poll_of_the_tweede_kamer_runs_its_chain_with_one_since(monkeypatch) -> None:
    ran, result = _ran(monkeypatch, ["tk", "--since", "2h"])
    assert not result.errors
    assert [address for address, _ in ran] == [
        "retrieve tk",
        "retrieve tk-dossiers",
        "retrieve tk-document-links",
        "normalize tk",
        "normalize tk-dossiers",
        "normalize tk-document-links",
        "semantic tk-dossier-outcomes",
        "semantic tk-government",
    ]
    since = {argv[-1] for _, argv in ran}
    assert len(since) == 1  # the window starts at one moment for every step
    moment = dt.datetime.fromisoformat(since.pop())
    ago = dt.datetime.now(dt.timezone.utc) - moment
    assert abs(ago - dt.timedelta(hours=2)) < dt.timedelta(seconds=5)
    assert "--skip-members" in dict(ran)["retrieve tk-dossiers"]
    # the steps that would read every dossier read what was touched since then
    moment = dict(ran)["normalize tk"][-1]
    for step in ("semantic tk-dossier-outcomes", "semantic tk-government"):
        assert dict(ran)[step] == ["--touched-since", moment]


def test_a_poll_of_the_rechtspraak_reads_the_courts_of_the_feed(monkeypatch) -> None:
    ran, _ = _ran(monkeypatch, ["rechtspraak", "--since", "3h"])
    argv = dict(ran)["retrieve rechtspraak"]
    courts = [argv[i + 1] for i, option in enumerate(argv) if option == "--court"]
    assert courts == list(FEED_TIERS)
    assert len(resolve_courts(courts)) == len(FEED_TIERS)  # each a known tier
    assert "--since" in dict(ran)["normalize rechtspraak"]


def test_a_poll_of_the_eerste_kamer_closes_the_dossiers_it_voted_on(
    monkeypatch,
) -> None:
    ran, _ = _ran(monkeypatch, ["ek", "--since", "2h"])
    assert [address for address, _ in ran] == [
        "retrieve eerstekamer-votes",
        "normalize eerstekamer-votes",
        "semantic tk-dossier-outcomes",
    ]


def test_a_poll_without_a_window_is_refused(monkeypatch) -> None:
    """A retrieve without --since reads everything there is."""
    with pytest.raises(SystemExit) as exc:
        _ran(monkeypatch, ["tk"])
    assert exc.value.code == 2


def test_a_failing_step_makes_the_poll_fail(monkeypatch) -> None:
    monkeypatch.setattr(
        poll,
        "run_pipelines",
        lambda pipelines, argv_of, **_: [
            Outcome(p.address, State.FAILED if p.phase == "retrieve" else State.OK)
            for p in pipelines
        ],
    )
    result = poll.main(["echr", "--since", "1d"])
    assert result.errors == ["retrieve echr failed"]


class _Recorder:
    """A retrieve pipeline that records what its command asked of it."""

    calls: list[dict] = []

    def __init__(self, *args, **kwargs) -> None:
        pass

    def run(self, **kwargs) -> PipelineResult:
        _Recorder.calls.append(kwargs)
        return PipelineResult()


@pytest.mark.parametrize("name", list(poll.POLLS))
def test_each_retrieve_of_a_poll_takes_its_options_and_reads_a_window(
    monkeypatch, name
) -> None:
    """The options are those of the retrieve command itself, and none of them reads
    everything (a since of None is the whole history)."""
    for cls in (
        "TKRetrievePipeline",
        "TKDossiersRetrievePipeline",
        "TKDocumentLinksRetrievePipeline",
        "RechtspraakRetrievePipeline",
        "ECHRRetrievePipeline",
        "EerstekamerVotesRetrievePipeline",
    ):
        monkeypatch.setattr(retrieve_commands, cls, _Recorder)
    monkeypatch.setattr(retrieve_commands, "GraphStore", lambda: object())
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=2)).isoformat()
    for pipeline, options in poll.chain(name):
        if pipeline.phase != "retrieve":
            continue
        _Recorder.calls = []
        pipeline.command(poll.argv_of(pipeline, options, since))
        (call,) = _Recorder.calls
        windows = {
            key: value
            for key, value in call.items()
            if key in ("since", "since_date", "date_from")
        }
        assert windows and all(value is not None for value in windows.values())


def test_only_a_poll_asks_for_what_was_touched() -> None:
    """The nightly ``semantic all --since last`` passes ``--since`` alone: these steps
    still read every dossier there, the safety net for what a poll does not see."""
    from lawgraph.pipelines.command import accepts_since, accepts_touched_since
    from lawgraph.sources.registry import find

    for name in ("tk-government", "tk-dossier-outcomes"):
        command = find("semantic", name).command  # type: ignore[union-attr]
        assert accepts_touched_since(command) and not accepts_since(command)

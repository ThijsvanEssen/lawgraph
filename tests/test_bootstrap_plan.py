"""The plan of ``lawgraph bootstrap``: every step once, in its lane, after what it reads."""

from __future__ import annotations

import datetime as dt
import re
from graphlib import TopologicalSorter
from pathlib import Path

import pytest

from lawgraph.commands import bootstrap_plan as bp
from lawgraph.sources import registry
from lawgraph.sources.registry import PIPELINES

SINCE = dt.datetime(2024, 10, 6, tzinfo=dt.timezone.utc)
PACKAGE = Path(registry.__file__).resolve().parents[1] / "pipelines"


@pytest.fixture(scope="module")
def plan() -> bp.Plan:
    return bp.make_plan("all", None)


def _step(plan: bp.Plan, label: str) -> bp.Step:
    return next(step for step in plan.steps if step.label == label)


# ── the steps ────────────────────────────────────────────────────────────────


def test_every_pipeline_is_a_step_once_and_the_build_ends_with_a_check(plan) -> None:
    labels = [step.label for step in plan.steps]
    every = [p.address for phase in PIPELINES.values() for p in phase]
    assert sorted(labels) == sorted(
        [a for a in every if a not in plan.left_out] + ["expand-graph", "check"]
    )
    assert labels[-2:] == ["expand-graph", "check"]


def test_a_retrieve_that_chooses_from_what_it_fetches_is_left_out(plan) -> None:
    """``retrieve eurlex`` fetches the acts already in the graph, which are what normalize
    eurlex makes of what it fetched: in a build there are none."""
    assert list(plan.left_out) == ["retrieve eurlex"]
    assert "expand-graph" in plan.left_out["retrieve eurlex"]
    assert "retrieve eurlex" not in _step(plan, "normalize eurlex").after


def test_every_wait_is_for_a_step_of_the_plan_and_none_goes_round(plan) -> None:
    labels = {step.label for step in plan.steps}
    for step in plan.steps:
        assert set(step.after) <= labels, step.label
    order = list(
        TopologicalSorter({s.label: s.after for s in plan.steps}).static_order()
    )
    assert order[-1] == "check"


def test_retrieves_run_in_the_lane_of_their_server_and_the_rest_in_the_write_lane(
    plan,
) -> None:
    for step in plan.steps:
        expected = (
            registry.find("retrieve", step.label.removeprefix("retrieve ")).lane_id  # type: ignore[union-attr]
            if step.label.startswith("retrieve ")
            else bp.WRITE_LANE
        )
        assert step.lane == expected, step.label
    assert list(plan.lanes())[-1] == bp.WRITE_LANE


def test_a_retrieve_that_reads_normalized_nodes_waits_for_their_normalize(plan) -> None:
    assert "normalize tk-dossiers" in _step(plan, "retrieve tk-content").after
    assert (
        "normalize eerstekamer-votes" in _step(plan, "retrieve eerstekamer-bills").after
    )


def test_a_normalize_waits_for_its_retrieve_what_feeds_it_and_what_it_comes_after(
    plan,
) -> None:
    assert _step(plan, "normalize tk").after == ("retrieve tk",)
    assert _step(plan, "normalize bwb").after == ("retrieve bwb", "retrieve tooi")
    assert _step(plan, "normalize rijksoverheid").after == (
        "retrieve rijksoverheid",
        "retrieve staatscourant-posts",
        "normalize tk-dossiers",
    )
    # normalize rechtspraak waits for nothing else: the others need not wait for it
    assert _step(plan, "normalize rechtspraak").after == ("retrieve rechtspraak",)


def test_the_semantic_phase_comes_after_everything_and_in_registry_order(plan) -> None:
    semantic = [s for s in plan.steps if s.label.startswith("semantic ")]
    assert [s.label for s in semantic] == [p.address for p in PIPELINES["semantic"]]
    first_after = set(semantic[0].after)
    assert {s.label for s in plan.steps if s.label.split()[0] != "semantic"} - {
        "expand-graph",
        "check",
    } == first_after
    for before, step in zip(semantic, semantic[1:], strict=False):
        assert step.after == (before.label,)
    assert _step(plan, "expand-graph").after == (semantic[-1].label,)


def test_the_window_reaches_the_producing_sources() -> None:
    whole = bp.make_plan("all", None)
    dated = bp.make_plan("2024-10-06", SINCE)
    assert _step(whole, "retrieve rechtspraak").argv == ("--mode", "full")
    assert _step(dated, "retrieve rechtspraak").argv == (
        "--mode",
        "incremental",
        "--since",
        SINCE.isoformat(),
    )
    assert _step(dated, "retrieve bwb").argv == ("--mode", "full")  # a reference source


def test_expand_graph_gets_its_rounds() -> None:
    plan = bp.make_plan("all", None, max_expand=2)
    assert _step(plan, "expand-graph").argv == ("--max-iterations", "2")


def test_what_feeds_a_normalize_is_the_retrieves_that_store_its_sources() -> None:
    """The sources a normalize module reads (``source=SOURCE_X``) are stored by the
    retrieve modules of its own name and of its ``fed_by``."""

    def sources(path: Path) -> set[str]:
        return set(re.findall(r"SOURCE_[A-Z_]+", path.read_text()))

    for pipeline in PIPELINES["normalize"]:
        module = PACKAGE / "normalize" / f"{pipeline.name.replace('-', '_')}.py"
        read = set(re.findall(r"source=(SOURCE_[A-Z_]+)", module.read_text()))
        stored: set[str] = set()
        for name in bp._feeding(pipeline):
            retrieve = registry.find("retrieve", name)
            if retrieve is None:
                continue
            # a part without a module of its own (bwb-history) runs from its source's
            own = PACKAGE / "retrieve" / f"{name.replace('-', '_')}.py"
            stored |= sources(
                own if own.exists() else PACKAGE / "retrieve" / f"{retrieve.source}.py"
            )
        assert read <= stored, (pipeline.name, read - stored)


# ── --plan ───────────────────────────────────────────────────────────────────


CODE = bp.Code("0.78.3", "build-0.78.3", "aaa")


def test_the_plan_names_its_window() -> None:
    assert bp.describe(bp.make_plan("730d", SINCE), {}, CODE).startswith(
        "Window of the producing sources: since 2024-10-06 (730d)."
    )
    assert bp.describe(bp.make_plan("all", None), {}, CODE).startswith(
        "Window of the producing sources: all: the whole history."
    )


def test_the_plan_says_what_is_done_and_on_which_code(plan) -> None:
    done = {
        "retrieve tk": bp.Mark("2026-10-06T08:00:00+00:00", 75, CODE),
        "normalize tk": bp.Mark(
            "2026-10-05T08:00:00+00:00", 4, bp.Code("0.78.2", "build-0.78.2", "bbb")
        ),
    }
    text = bp.describe(plan, done, CODE)
    assert f"2 of {len(plan.steps)} steps done." in text
    lines = {
        " ".join(line.split()[:2]): line
        for line in text.splitlines()
        if line.startswith("  ")
    }
    assert lines["retrieve tk"].endswith("done 2026-10-06T08:00:00+00:00 in 1m15s")
    assert lines["normalize tk"].endswith("on 0.78.2 (build-0.78.2)")
    assert lines["retrieve tk-dossiers"].endswith("retrieve tk-dossiers")  # nothing yet
    assert "left out:" in text and "retrieve eurlex:" in text


def test_code_without_a_checkout_is_unknown() -> None:
    assert str(bp.Code(None, None, None)) == "unknown code"
    assert bp._git(Path("/nonexistent"), "rev-parse", "HEAD") is None

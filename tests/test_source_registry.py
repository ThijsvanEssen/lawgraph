"""The registry: every pipeline has one address, derived from where it lives."""

from __future__ import annotations

from pathlib import Path

import pytest

from lawgraph.config.settings import skip_step, skip_variable
from lawgraph.core.models import PipelineResult
from lawgraph.sources import registry
from lawgraph.sources.registry import PHASES, PIPELINES, SOURCES, _address_of, _pipeline

PACKAGE = Path(registry.__file__).resolve().parents[1] / "pipelines"


def _order(phase: str) -> list[str]:
    return [pipeline.name for pipeline in PIPELINES[phase]]  # type: ignore[index]


# ── the address ──────────────────────────────────────────────────────────────


def test_an_address_is_read_from_the_module_never_written() -> None:
    semantic = "lawgraph.pipelines.semantic."
    assert _address_of(semantic + "rechtspraak_citations", "") == (
        "semantic",
        "rechtspraak",
        "citations",
    )
    assert _address_of(semantic + "tk_amendment_articles", "")[1:] == (
        "tk",
        "amendment-articles",
    )
    assert _address_of("lawgraph.pipelines.normalize.bwb", "") == (
        "normalize",
        "bwb",
        None,
    )
    commands = "lawgraph.pipelines.retrieve_commands"
    assert _address_of(commands, "retrieve_tk_dossiers") == (
        "retrieve",
        "tk",
        "dossiers",
    )


def test_a_module_that_names_no_source_is_refused() -> None:
    with pytest.raises(ValueError, match="does not start with a source"):
        _address_of("lawgraph.pipelines.semantic.judgment_citations", "")


def test_a_class_that_is_not_named_after_its_address_is_refused() -> None:
    """At import, so the program does not start: not a test that fails one day."""

    class JudgmentCitationsSemanticPipeline:
        __module__ = "lawgraph.pipelines.semantic.rechtspraak_citations"

        def run(self) -> PipelineResult:
            return PipelineResult()

    with pytest.raises(
        ValueError, match="is called RechtspraakCitationsSemanticPipeline"
    ):
        _pipeline(JudgmentCitationsSemanticPipeline, "")


def test_addresses_are_unique_and_belong_to_a_known_source() -> None:
    addresses = [p.address for phase in PHASES for p in PIPELINES[phase]]
    assert len(addresses) == len(set(addresses))
    assert {p.source for phase in PHASES for p in PIPELINES[phase]} <= set(SOURCES)


def test_every_module_of_a_phase_is_a_pipeline_or_starts_with_an_underscore() -> None:
    """In a directory listing, what has no underscore is an address."""
    for phase in ("normalize", "semantic"):
        modules = {
            path.stem.replace("_", "-")
            for path in (PACKAGE / phase).glob("*.py")
            if not path.stem.startswith("_") and path.stem != "base"
        }
        assert modules == set(_order(phase)), phase


def test_the_skip_variable_is_the_address_in_capitals(monkeypatch) -> None:
    assert (
        skip_variable("normalize", "tk-dossiers")
        == "LAWGRAPH_NORMALIZE_SKIP_TK_DOSSIERS"
    )
    monkeypatch.setenv("LAWGRAPH_NORMALIZE_SKIP_TK_DOSSIERS", "true")
    assert skip_step("normalize", "tk-dossiers")
    assert not skip_step("semantic", "tk-dossiers")


def test_a_manual_retrieve_pipeline_has_no_options_for_retrieve_all() -> None:
    manual = {p.name for p in PIPELINES["retrieve"] if p.argv_for_all is None}
    assert manual == {"bwb-history", "tk-content"}


# ── the order of a phase ─────────────────────────────────────────────────────


def test_normalize_order_puts_what_is_looked_up_first() -> None:
    """An edge to a node that does not exist yet is left out, and an incremental run does not
    come back for it."""
    order = _order("normalize")
    # documents, activities and decisions are linked to the cases that exist
    assert order.index("tk") < order.index("tk-dossiers")
    # the history only adds seed instruments for the regulations bwb did not load
    assert order.index("bwb") < order.index("bwb-history")


def test_semantic_order_puts_what_is_read_first() -> None:
    order = _order("semantic")
    # bwb-relation-types classifies the REFERS_TO edges made by bwb
    assert order.index("bwb") < order.index("bwb-relation-types")
    assert order.index("bwb") < order.index("bwb-annexes")
    # amendment edges need the articles from bwb and the grondslagen run before them
    assert order.index("bwb") < order.index("bwb-amendments")
    assert order.index("bwb-grondslagen") < order.index("bwb-amendments")
    # tk-amendment-articles starts from the AMENDS edges of tk-amends
    assert order.index("tk-amends") < order.index("tk-amendment-articles")
    # the counts of graph-list-stats are those of every edge written before it
    assert order[-1] == "graph-list-stats"


def test_the_documented_skip_variables_are_those_of_the_pipelines_a_phase_runs() -> (
    None
):
    """docs/operations.md named seven semantic pipelines by names they no longer had."""
    import re
    from pathlib import Path

    from lawgraph.config.settings import skip_variable
    from lawgraph.sources.registry import PIPELINES

    text = (Path(__file__).resolve().parents[1] / "docs" / "operations.md").read_text()
    names = {p.name for p in PIPELINES["retrieve"] if p.argv_for_all is not None}
    rows = {
        "retrieve": names,
        # "the same without WIKIDATA, plus"
        "normalize": names - {"wikidata"} | {"bwb-history", "tk-content"},
        "semantic": {p.name for p in PIPELINES["semantic"]},
    }
    for phase in ("retrieve", "semantic"):
        row = re.search(rf"^\| `{phase.upper()}` \| (.*) \|$", text, re.MULTILINE)
        assert row, phase
        documented = set(re.findall(r"`([A-Z_]+)`", row.group(1)))
        expected = {skip_variable(phase, n).split("_SKIP_")[1] for n in rows[phase]}
        assert documented == expected, phase
    assert {p.name for p in PIPELINES["normalize"]} == rows["normalize"]

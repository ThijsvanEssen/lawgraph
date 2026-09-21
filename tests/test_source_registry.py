"""The source registry is the single place that defines CLI commands and their order."""

from __future__ import annotations

from lawgraph.__main__ import _build_dispatch
from lawgraph.config.settings import skip_step, skip_variable
from lawgraph.sources.registry import SOURCES


def _cli_keys(phase_attr: str) -> set[str]:
    return {s.id.replace("_", "-") for s in SOURCES if getattr(s, phase_attr)}


def test_source_ids_are_unique() -> None:
    ids = [s.id for s in SOURCES]
    assert len(ids) == len(set(ids))


def test_cli_commands_come_only_from_the_registry() -> None:
    dispatch = _build_dispatch()

    assert set(dispatch["retrieve"]) == _cli_keys("retrieve_command") | {"all"}
    assert set(dispatch["normalize"]) == _cli_keys("normalize_command") | {"all"}
    assert set(dispatch["semantic"]) == _cli_keys("semantic_command") | {"all"}


def test_manual_retrieve_sources_are_not_part_of_retrieve_all() -> None:
    in_retrieve_all = {
        s.id
        for s in SOURCES
        if s.retrieve_command is not None and s.retrieve_argv_builder is not None
    }

    assert {"bwb_history", "tk_content"}.isdisjoint(in_retrieve_all)
    assert {"bwb_history", "tk_content"} <= {
        s.id for s in SOURCES if s.retrieve_command is not None
    }


def test_skip_variables_follow_one_naming_scheme(monkeypatch) -> None:
    assert (
        skip_variable("normalize", "tk_dossiers")
        == "LAWGRAPH_NORMALIZE_SKIP_TK_DOSSIERS"
    )

    monkeypatch.setenv("LAWGRAPH_NORMALIZE_SKIP_TK_DOSSIERS", "True")
    assert skip_step("normalize", "tk_dossiers")
    assert not skip_step("semantic", "tk_dossiers")


def test_list_stats_runs_after_every_edge_writing_step() -> None:
    assert [s.id for s in SOURCES if s.semantic_command is not None][-1] == "list_stats"


def test_semantic_order_puts_dependencies_first() -> None:
    order = [s.id for s in SOURCES if s.semantic_command is not None]

    # relation_semantics classifies the REFERS_TO edges made by bwb
    assert order.index("bwb") < order.index("relation_semantics")
    # annex links need articles/instruments from normalize, and run with bwb data
    assert order.index("bwb") < order.index("bwb_annexes")
    # amendment edges need the articles from bwb and the grondslagen run before them
    assert order.index("bwb") < order.index("bwb_amendments")
    assert order.index("bwb_grondslagen") < order.index("bwb_amendments")


def test_normalize_order_puts_what_is_looked_up_first() -> None:
    """An edge to a node that does not exist yet is left out, and an incremental run does not
    come back for it."""
    order = [s.id for s in SOURCES if s.normalize_command is not None]

    # documents, activities and decisions are linked to the cases that exist
    assert order.index("tk") < order.index("tk_dossiers")
    # the history only adds seed instruments for the regulations bwb did not load
    assert order.index("bwb") < order.index("bwb_history")


def test_semantic_order_of_the_steps_that_read_other_steps() -> None:
    order = [s.id for s in SOURCES if s.semantic_command is not None]

    # amendment-articles starts from the AMENDS edges of instrument-relations
    assert order.index("instrument_relations") < order.index("amendment_articles")
    # the counts of list-stats are those of every edge written before it
    assert order[-1] == "list_stats"

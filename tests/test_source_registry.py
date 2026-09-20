"""The source registry is the single place that defines CLI commands and their order."""

from __future__ import annotations

from lawgraph.__main__ import _build_dispatch
from lawgraph.sources.registry import SOURCES


def _cli_keys(phase_attr: str) -> set[str]:
    return {s.id.replace("_", "-") for s in SOURCES if getattr(s, phase_attr)}


def test_source_ids_are_unique() -> None:
    ids = [s.id for s in SOURCES]
    assert len(ids) == len(set(ids))


def test_cli_commands_come_only_from_the_registry() -> None:
    dispatch = _build_dispatch()

    assert set(dispatch["retrieve"]) == _cli_keys("retrieve_main") | {"all"}
    assert set(dispatch["normalize"]) == _cli_keys("normalize_main") | {"all"}
    assert set(dispatch["semantic"]) == _cli_keys("semantic_main") | {"all"}


def test_manual_retrieve_sources_are_not_part_of_retrieve_all() -> None:
    in_retrieve_all = {
        s.id
        for s in SOURCES
        if s.retrieve_main is not None and s.retrieve_argv_builder is not None
    }

    assert {"bwb_history", "tk_content"}.isdisjoint(in_retrieve_all)
    assert {"bwb_history", "tk_content"} <= {
        s.id for s in SOURCES if s.retrieve_main is not None
    }


def test_skip_env_vars_follow_one_naming_scheme() -> None:
    for s in SOURCES:
        for phase in ("retrieve", "normalize", "semantic"):
            if getattr(s, f"{phase}_main") is None:
                continue
            env = getattr(s, f"{phase}_skip_env")
            if env is None:  # manual-only retrieve sources
                assert phase == "retrieve", s.id
                continue
            assert env == f"LAWGRAPH_{phase.upper()}_SKIP_{s.id.upper()}", s.id


def test_semantic_order_puts_dependencies_first() -> None:
    order = [s.id for s in SOURCES if s.semantic_main is not None]

    # relation_semantics classifies the REFERS_TO edges made by bwb
    assert order.index("bwb") < order.index("relation_semantics")
    # annex links need articles/instruments from normalize, and run with bwb data
    assert order.index("bwb") < order.index("bwb_annexes")
    # amendment edges need the articles from bwb and the grondslagen run before them
    assert order.index("bwb") < order.index("bwb_amendments")
    assert order.index("bwb_grondslagen") < order.index("bwb_amendments")

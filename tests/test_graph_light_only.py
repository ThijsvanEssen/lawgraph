"""``semantic graph-light --only``: the light tables named, the others left alone (after a
release that changed what one of them derives, as ``lg_signed_date`` for ``lg_authored``)."""

from __future__ import annotations

import argparse
from typing import Any

import pytest

from lawgraph.pipelines.semantic import graph_light


def _recording(monkeypatch: pytest.MonkeyPatch) -> list[tuple[str, bool]]:
    calls: list[tuple[str, bool]] = []

    def fill_of(name: str) -> Any:
        def fill(store: Any, *, every: bool = False) -> int:
            calls.append((name, every))
            return 1

        return fill

    monkeypatch.setattr(
        graph_light,
        "_FILLS",
        tuple(f._replace(fill=fill_of(f.name)) for f in graph_light._FILLS),
    )
    return calls


def test_only_the_tables_named_are_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _recording(monkeypatch)
    pipeline = graph_light.GraphLightSemanticPipeline(
        store=None,  # type: ignore[arg-type]
        every=True,
        only=("authored", "led"),
    )
    assert pipeline.run().updated == 2
    assert calls == [("authored", True), ("led", True)]


def test_without_only_every_table_is_kept(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _recording(monkeypatch)
    graph_light.GraphLightSemanticPipeline(store=None).run()  # type: ignore[arg-type]
    assert [name for name, _ in calls] == [f.name for f in graph_light._FILLS]


def test_only_takes_the_names_of_the_tables() -> None:
    parser = argparse.ArgumentParser()
    graph_light.add_args(parser)
    args = parser.parse_args(["--all", "--only", "authored,led"])
    assert graph_light.extra_kwargs(args)["only"] == ("authored", "led")
    with pytest.raises(SystemExit):
        parser.parse_args(["--only", "authored,nothing"])

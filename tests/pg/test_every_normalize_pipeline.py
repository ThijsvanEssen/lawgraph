"""Every registered normalize pipeline runs on an empty graph: nothing to read, nothing
written, nothing left out."""

from __future__ import annotations

from lawgraph.db import GraphStore
from lawgraph.pipelines.command import PipelineCommand
from lawgraph.sources.registry import PIPELINES


def test_every_normalize_pipeline_runs_on_an_empty_graph(store: GraphStore) -> None:
    ran = []
    for pipeline in PIPELINES["normalize"]:
        assert isinstance(pipeline.command, PipelineCommand), pipeline.address
        result = pipeline.command.pipeline_cls(store=store).run()

        counts = (result.created, result.updated, result.skipped, result.errors)
        assert counts == (0, 0, 0, []), pipeline.address
        ran.append(pipeline.name)
    assert "tk-dossiers" in ran and "bwb-history" in ran

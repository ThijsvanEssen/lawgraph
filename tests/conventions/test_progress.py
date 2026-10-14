"""Every pipeline reports its progress."""

from __future__ import annotations

from tests.conventions._scan import SRC


def test_every_pipeline_reports_progress() -> None:
    """One implementation (core/progress.py): a live line in a terminal, a line a minute in a
    log file, a summary at the end. A pipeline reaches it through the reader of its phase."""
    pipelines = SRC / "pipelines"
    ways = {
        # the one retrieve loop, through ``fetch`` or called by name; tk-content updates
        "retrieve": ("def fetch(", "_store_all(", "Progress("),
        # the tracked raw readers, or the base that reads through them
        "normalize": ("_iter_raw_sources(", "RawRecords(", "(LinkRecordsPipelineBase)"),
        "semantic": (
            "self._track(",
            "self._judgment_texts(",
            "self._judgment_paragraphs(",
        ),
    }
    silent = []
    for phase, calls in ways.items():
        for path in sorted((pipelines / phase).glob("*.py")):
            text = path.read_text()
            if "PipelineBase):" not in text or path.name == "base.py":
                continue  # helpers and detectors, not a pipeline
            if path.name.startswith("graph_"):
                continue  # a statement per table or collection, no loop over records
            if not any(call in text for call in calls) and "super().run(" not in text:
                silent.append(f"{phase}/{path.name}")
    assert "Progress(" in (pipelines / "semantic" / "graph_list_stats.py").read_text()
    assert not silent, f"no progress reported by: {silent}"

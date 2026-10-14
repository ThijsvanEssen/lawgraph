"""``lawgraph courts build|check``: the court table from the Instanties value list.

``build`` reads the stored value list (``retrieve rechtspraak-instanties``), makes the table
with ``core.court_sources.build_courts``, writes it (``--output``, else that file) and
prints what changed.
``check`` prints the same and writes nothing; a difference fails it, so a run after
``retrieve rechtspraak-instanties`` shows when the list has changed. Commit the file a build
writes; a court that changes tier or kind needs ``semantic graph-list-stats`` after.
"""

from __future__ import annotations

from lawgraph.commands._data_file import (
    Document,
    build_or_check,
    keyed_differences,
    stored_records,
)
from lawgraph.config.constants import RAW_KIND_RS_INSTANTIES, SOURCE_RECHTSPRAAK
from lawgraph.core.court_sources import build_courts
from lawgraph.core.courts import DATA
from lawgraph.core.models import PipelineResult
from lawgraph.core.raw_records import meta, payload_text
from lawgraph.db import GraphStore


def main(argv: list[str] | None = None) -> PipelineResult:
    return build_or_check(
        argv,
        doc=__doc__,
        data=DATA,
        name="courts",
        rebuild=rebuild,
        differences=lambda before, after: keyed_differences(
            before["courts"], after["courts"], "code"
        ),
    )


def rebuild(store: GraphStore, current: Document) -> Document:
    """*current* (the content of ``data/courts.json``) built again from the stored value
    list. Raises when it was never retrieved."""
    record: Document | None = next(
        stored_records(store, SOURCE_RECHTSPRAAK, RAW_KIND_RS_INSTANTIES), None
    )
    if record is None:
        raise RuntimeError("Run `retrieve rechtspraak-instanties` first.")
    about = meta(record)
    return {
        **current,
        "sources": {
            SOURCE_RECHTSPRAAK: {
                "url": about.get("url"),
                "read_on": about.get("read_on"),
            }
        },
        "courts": build_courts(payload_text(record) or ""),
    }

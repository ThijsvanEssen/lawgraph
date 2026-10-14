"""``lawgraph ministries build|check``: the ministry table from the official sources.

``build`` reads the stored TOOI value list (``retrieve tooi``) and the stored Rijksoverheid
cabinet pages (``retrieve rijksoverheid``), makes the table with
``core.ministry_sources.build_ministries`` with the curated keys, order and successions
(``data/curated/ministries.json``), writes it (``--output``, else ``data/ministries.json``) and
prints what changed, and every curated name no source names. ``check`` prints the same and
writes nothing; a difference fails it, so a run after ``retrieve tooi`` shows when TOOI has
changed. Commit the file a build writes.
"""

from __future__ import annotations

from typing import Any

from lawgraph.commands._data_file import (
    Document,
    build_or_check,
    keyed_differences,
    stored_records,
)
from lawgraph.config.constants import (
    RAW_KIND_RIJKSOVERHEID_CABINET,
    RAW_KIND_TOOI_MINISTRIES,
    SOURCE_RIJKSOVERHEID,
    SOURCE_TOOI,
)
from lawgraph.core.cabinet_sources import build_cabinets
from lawgraph.core.curated import LISTS
from lawgraph.core.ministries import DATA
from lawgraph.core.ministry_sources import build_ministries
from lawgraph.core.models import PipelineResult
from lawgraph.core.raw_records import meta, payload_json, payload_text
from lawgraph.core.rijksoverheid import parse_page
from lawgraph.db import GraphStore


def main(argv: list[str] | None = None) -> PipelineResult:
    return build_or_check(
        argv,
        doc=__doc__,
        data=DATA,
        name="ministries",
        rebuild=_rebuilt_saying_what_was_dropped,
        differences=lambda before, after: keyed_differences(
            before["ministries"], after["ministries"], "key"
        ),
    )


def _rebuilt_saying_what_was_dropped(store: GraphStore, current: Document) -> Document:
    rebuilt, dropped = rebuild(store, current, LISTS["ministries"].document())
    for key in dropped:
        print(f"! {key}: curated, but no source names it; left out.")
    return rebuilt


def rebuild(
    store: GraphStore, current: dict[str, Any], curated: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """*current* (the content of ``data/ministries.json``) built again from the stored
    sources and *curated*, and the curated keys no source names. Raises when a source was
    never retrieved."""
    tooi = list(stored_records(store, SOURCE_TOOI, RAW_KIND_TOOI_MINISTRIES))
    pages = list(
        stored_records(store, SOURCE_RIJKSOVERHEID, RAW_KIND_RIJKSOVERHEID_CABINET)
    )
    if not tooi or not pages:
        raise RuntimeError("Run `retrieve tooi` and `retrieve rijksoverheid` first.")
    cabinets = build_cabinets(
        [
            {
                "slug": r.get("external_id"),
                "url": meta(r).get("url"),
                "read_on": meta(r).get("read_on"),
                "page": parse_page(payload_text(r) or ""),
            }
            for r in pages
        ],
        lambda text: None,
    )
    about = meta(tooi[0])
    table, dropped = build_ministries(
        curated, payload_json(tooi[0]).get("items") or [], cabinets
    )
    return {
        **current,
        "sources": {
            SOURCE_TOOI: {"url": about.get("url"), "read_on": about.get("read_on")},
            SOURCE_RIJKSOVERHEID: {
                "url": current["sources"][SOURCE_RIJKSOVERHEID]["url"],
                "read_on": max(meta(r).get("read_on") or "" for r in pages) or None,
            },
        },
        "ministries": table,
    }, dropped

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

import argparse
import json
from pathlib import Path
from typing import Any

from lawgraph.config.constants import (
    RAW_KIND_RIJKSOVERHEID_CABINET,
    RAW_KIND_TOOI_MINISTRIES,
    SOURCE_RIJKSOVERHEID,
    SOURCE_TOOI,
)
from lawgraph.core.cabinet_sources import build_cabinets
from lawgraph.core.ministries import CURATED, DATA
from lawgraph.core.ministry_sources import build_ministries
from lawgraph.core.models import PipelineResult
from lawgraph.core.raw_records import meta, payload_json, payload_text
from lawgraph.core.rijksoverheid import parse_page
from lawgraph.db import GraphStore
from lawgraph.db.queries import raw as raw_queries


def main(argv: list[str] | None = None) -> PipelineResult:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("action", choices=["build", "check"])
    parser.add_argument(
        "--output",
        type=Path,
        default=DATA,
        help="Where build writes (default: %(default)s).",
    )
    args = parser.parse_args(argv)
    result = PipelineResult()
    current = json.loads(DATA.read_text(encoding="utf-8"))
    curated = json.loads(CURATED.read_text(encoding="utf-8"))
    rebuilt, dropped = rebuild(GraphStore(), current, curated)
    changes = differences(current["ministries"], rebuilt["ministries"])
    for key in dropped:
        print(f"! {key}: curated, but no source names it; left out.")
    for line in changes:
        print(line)
    print(f"{len(changes)} changes.")
    if args.action == "build":
        args.output.write_text(
            json.dumps(rebuilt, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
        print(f"Wrote {args.output}.")
    elif changes:
        result.add_error(
            f"{len(changes)} changes against {DATA}: run `ministries build`."
        )
    return result


def _records(store: GraphStore, source: str, kind: str) -> list[dict[str, Any]]:
    rows = raw_queries.iter_raw_records(
        store, source=source, kinds=[kind], since_iso=None, batch_size=50
    )
    return list(store.with_payloads(rows))


def rebuild(
    store: GraphStore, current: dict[str, Any], curated: dict[str, Any]
) -> tuple[dict[str, Any], list[str]]:
    """*current* (the content of ``data/ministries.json``) built again from the stored
    sources and *curated*, and the curated keys no source names. Raises when a source was
    never retrieved."""
    tooi = _records(store, SOURCE_TOOI, RAW_KIND_TOOI_MINISTRIES)
    pages = _records(store, SOURCE_RIJKSOVERHEID, RAW_KIND_RIJKSOVERHEID_CABINET)
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


def differences(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> list[str]:
    """One line per ministry added, removed or changed."""
    old = {m["key"]: m for m in before}
    new = {m["key"]: m for m in after}
    lines = [f"+ {k}: {new[k]['name']}" for k in new if k not in old]
    lines += [f"- {k}: {old[k]['name']}" for k in old if k not in new]
    lines += [
        f"~ {k}: {json.dumps(old[k], ensure_ascii=False)} -> "
        f"{json.dumps(new[k], ensure_ascii=False)}"
        for k in new
        if k in old and new[k] != old[k]
    ]
    return lines

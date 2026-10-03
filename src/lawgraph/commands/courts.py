"""``lawgraph courts build|check``: the court table from the Instanties value list.

``build`` reads the stored value list (``retrieve rechtspraak-instanties``), makes the table
with ``core.court_sources.build_courts``, writes it (``--output``, else that file) and
prints what changed.
``check`` prints the same and writes nothing; a difference fails it, so a run after
``retrieve rechtspraak-instanties`` shows when the list has changed. Commit the file a build
writes; a court that changes tier or kind needs ``semantic graph-list-stats`` after.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from lawgraph.config.constants import RAW_KIND_RS_INSTANTIES, SOURCE_RECHTSPRAAK
from lawgraph.core.court_sources import build_courts
from lawgraph.core.courts import DATA
from lawgraph.core.models import PipelineResult
from lawgraph.core.raw_records import meta, payload_text
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
    rebuilt = rebuild(GraphStore(), current)
    changes = differences(current["courts"], rebuilt["courts"])
    for line in changes:
        print(line)
    print(f"{len(changes)} changes.")
    if args.action == "build":
        args.output.write_text(
            json.dumps(rebuilt, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
        print(f"Wrote {args.output}.")
    elif changes:
        result.add_error(f"{len(changes)} changes against {DATA}: run `courts build`.")
    return result


def rebuild(store: GraphStore, current: dict[str, Any]) -> dict[str, Any]:
    """*current* (the content of ``data/courts.json``) built again from the stored value
    list. Raises when it was never retrieved."""
    rows = raw_queries.iter_raw_records(
        store,
        source=SOURCE_RECHTSPRAAK,
        kinds=[RAW_KIND_RS_INSTANTIES],
        since_iso=None,
        batch_size=1,
    )
    records = list(store.with_payloads(rows))
    if not records:
        raise RuntimeError("Run `retrieve rechtspraak-instanties` first.")
    about = meta(records[0])
    return {
        **current,
        "sources": {
            SOURCE_RECHTSPRAAK: {
                "url": about.get("url"),
                "read_on": about.get("read_on"),
            }
        },
        "courts": build_courts(payload_text(records[0]) or ""),
    }


def differences(before: list[dict[str, Any]], after: list[dict[str, Any]]) -> list[str]:
    """One line per court added, removed or changed."""
    old = {c["code"]: c for c in before}
    new = {c["code"]: c for c in after}
    lines = [f"+ {k}: {new[k]['name']}" for k in new if k not in old]
    lines += [f"- {k}: {old[k]['name']}" for k in old if k not in new]
    lines += [
        f"~ {k}: {json.dumps(old[k], ensure_ascii=False)} -> "
        f"{json.dumps(new[k], ensure_ascii=False)}"
        for k in new
        if k in old and new[k] != old[k]
    ]
    return lines

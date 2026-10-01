"""``lawgraph code-families build|check``: the codes whose books are regulations of their own.

``build`` reads the stored WTI records (``retrieve bwb``), makes the families with
``core.code_families.families_from_wti``, writes them (``--output``, else
``data/code_families.json``) and prints what changed. ``check`` prints the same and writes
nothing; a difference fails it. Commit the file a build writes.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from lawgraph.config.constants import RAW_KIND_BWB_WTI_GENERAL, SOURCE_BWB
from lawgraph.core.bwb_wti import parse_abbreviations
from lawgraph.core.code_families import DATA, families_from_wti
from lawgraph.core.models import PipelineResult
from lawgraph.core.raw_records import payload_text
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
    changes = differences(current["families"], rebuilt["families"])
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
            f"{len(changes)} changes against {DATA}: run `code-families build`."
        )
    return result


def rebuild(store: GraphStore, current: dict[str, Any]) -> dict[str, Any]:
    """*current* (the content of ``data/code_families.json``) built again from the stored
    WTI records. Raises when none was stored."""
    rows = raw_queries.iter_raw_records(
        store,
        source=SOURCE_BWB,
        kinds=[RAW_KIND_BWB_WTI_GENERAL],
        since_iso=None,
        batch_size=1000,
    )
    abbreviations: dict[str, list[str]] = {}
    read_on = ""
    for record in store.with_payloads(rows):
        text = payload_text(record)
        if text:
            abbreviations[record["external_id"]] = parse_abbreviations(text)
            read_on = max(read_on, (record.get("fetched_at") or "")[:10])
    if not abbreviations:
        raise RuntimeError("Run `retrieve bwb` first: no WTI record is stored.")
    return {
        **current,
        "sources": {
            SOURCE_BWB: {**current["sources"][SOURCE_BWB], "read_on": read_on or None}
        },
        "families": families_from_wti(abbreviations),
    }


def differences(
    before: dict[str, dict[str, str]], after: dict[str, dict[str, str]]
) -> list[str]:
    """One line per book added, removed or moved to another regulation."""
    old = {
        (code, book): i for code, books in before.items() for book, i in books.items()
    }
    new = {
        (code, book): i for code, books in after.items() for book, i in books.items()
    }
    lines = [f"+ {c} {b}: {new[c, b]}" for c, b in new if (c, b) not in old]
    lines += [f"- {c} {b}: {old[c, b]}" for c, b in old if (c, b) not in new]
    lines += [
        f"~ {c} {b}: {old[c, b]} -> {new[c, b]}"
        for c, b in new
        if (c, b) in old and old[c, b] != new[c, b]
    ]
    return lines

"""A data file built from stored records (``lawgraph courts|ministries|code-families``).

``build`` makes the file again from what the retrieves stored, writes it (``--output``, else
the file itself) and prints what changed; ``check`` prints the same and writes nothing, and
a difference fails it. Each command gives how to make the file again and how to say what
changed.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

from lawgraph.config.constants import RAW_BATCH_SIZE
from lawgraph.core.models import PipelineResult
from lawgraph.db import GraphStore
from lawgraph.db.queries import raw as raw_queries
from lawgraph.pipelines.command import command_parser, docstring_title

Document = dict[str, Any]


def build_or_check(
    argv: list[str] | None,
    *,
    doc: str | None,
    data: Path,
    name: str,
    rebuild: Callable[[GraphStore, Document], Document],
    differences: Callable[[Document, Document], list[str]],
) -> PipelineResult:
    """The command ``lawgraph <name> build|check`` of the file *data*: *doc* is its
    docstring, *rebuild* makes the file again from the graph."""
    parser = command_parser(docstring_title(doc))
    parser.add_argument("action", choices=["build", "check"])
    parser.add_argument(
        "--output",
        type=Path,
        default=data,
        help="Where build writes (default: %(default)s).",
    )
    args = parser.parse_args(argv)
    result = PipelineResult()
    current = json.loads(data.read_text(encoding="utf-8"))
    rebuilt = rebuild(GraphStore(), current)
    changes = differences(current, rebuilt)
    for line in changes:
        print(line)
    print(f"{len(changes)} changes.")
    if args.action == "build":
        args.output.write_text(
            json.dumps(rebuilt, ensure_ascii=False, indent=1) + "\n", encoding="utf-8"
        )
        print(f"Wrote {args.output}.")
    elif changes:
        result.add_error(f"{len(changes)} changes against {data}: run `{name} build`.")
    return result


def keyed_differences(
    before: list[Document], after: list[Document], key: str
) -> list[str]:
    """One line per row added, removed or changed, rows known by their *key*."""
    old = {row[key]: row for row in before}
    new = {row[key]: row for row in after}
    lines = [f"+ {k}: {new[k]['name']}" for k in new if k not in old]
    lines += [f"- {k}: {old[k]['name']}" for k in old if k not in new]
    lines += [
        f"~ {k}: {json.dumps(old[k], ensure_ascii=False)} -> "
        f"{json.dumps(new[k], ensure_ascii=False)}"
        for k in new
        if k in old and new[k] != old[k]
    ]
    return lines


def stored_records(store: GraphStore, source: str, kind: str) -> Iterator[Document]:
    """The stored records of *kind* from *source*, each with its payload."""
    rows = raw_queries.iter_raw_records(
        store,
        source=source,
        kinds=[kind],
        since_iso=None,
        batch_size=RAW_BATCH_SIZE[kind],
    )
    return store.with_payloads(rows)

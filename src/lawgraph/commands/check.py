"""``lawgraph check``: is the database what the pipelines should have made of the sources?

A step can end "successfully" and still leave nothing behind: a source that answers no records
for a parameter it does not understand, a normalize step that was never run, a search view
that lost its index when the server was killed. Nothing complains about that on its own; this
command does. Every check is one read-only query, and it exits 1 when one of them fails:

  raw      every raw kind of the registry holds records
  nodes    every source with raw records has nodes (normalize did run and wrote something)
  edges    no edge points to a node that does not exist
  views    every search view holds what its collection holds (``out of sync`` after a crash)
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field

from lawgraph.config.constants import (
    COLLECTION_CASES,
    COLLECTION_DOCUMENTS,
    COLLECTION_EDGES,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    COLLECTION_RAW_SOURCES,
    RAW_KIND_BWB_TOESTAND,
    RAW_KIND_BWB_TOESTAND_ALL,
    RAW_KIND_ECHR_JUDGMENT,
    RAW_KIND_EK_KAMERSTUK,
    RAW_KIND_EU_CELEX,
    RAW_KIND_RS_CONTENT,
    RAW_KIND_STB_AMVB,
    RAW_KIND_STCRT_REGELING,
    RAW_KIND_TK_ZAAK,
    RAW_KIND_VERDRAG,
    RAW_SOURCE_KINDS,
    SOURCE_BWB,
    SOURCE_ECHR,
    SOURCE_EERSTEKAMER,
    SOURCE_EURLEX,
    SOURCE_RECHTSPRAAK,
    SOURCE_STAATSBLAD,
    SOURCE_STAATSCOURANT,
    SOURCE_TK,
    SOURCE_VERDRAGENBANK,
)
from lawgraph.core.logging import get_logger, setup_logging
from lawgraph.db import ArangoStore
from lawgraph.db.schema import SEARCH_VIEWS

logger = get_logger(__name__)

# Where the nodes of a source go; ``props.source`` names the source on every node.
NODES_OF_SOURCE = {
    SOURCE_TK: COLLECTION_CASES,
    SOURCE_RECHTSPRAAK: COLLECTION_JUDGMENTS,
    SOURCE_ECHR: COLLECTION_JUDGMENTS,
    SOURCE_EURLEX: COLLECTION_INSTRUMENTS,
    SOURCE_BWB: COLLECTION_INSTRUMENTS,
    SOURCE_VERDRAGENBANK: COLLECTION_INSTRUMENTS,
    SOURCE_STAATSBLAD: COLLECTION_DOCUMENTS,
    SOURCE_STAATSCOURANT: COLLECTION_DOCUMENTS,
    SOURCE_EERSTEKAMER: COLLECTION_DOCUMENTS,
}
# The raw kind of which every record becomes one node there, and the share of them that
# must have one (a few records have no usable payload and are skipped).
RECORD_KIND = {
    SOURCE_TK: RAW_KIND_TK_ZAAK,
    SOURCE_RECHTSPRAAK: RAW_KIND_RS_CONTENT,
    SOURCE_ECHR: RAW_KIND_ECHR_JUDGMENT,
    SOURCE_EURLEX: RAW_KIND_EU_CELEX,
    SOURCE_BWB: RAW_KIND_BWB_TOESTAND,
    SOURCE_VERDRAGENBANK: RAW_KIND_VERDRAG,
    SOURCE_STAATSBLAD: RAW_KIND_STB_AMVB,
    SOURCE_STAATSCOURANT: RAW_KIND_STCRT_REGELING,
    SOURCE_EERSTEKAMER: RAW_KIND_EK_KAMERSTUK,
}
NORMALIZED_SHARE = 0.9
# Kinds that are only there after a manual command; their absence says nothing.
OPTIONAL_KINDS = {RAW_KIND_BWB_TOESTAND_ALL}


@dataclass
class Report:
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def problem(self, message: str) -> None:
        self.problems.append(message)
        logger.error("%s", message)

    def note(self, message: str) -> None:
        self.notes.append(message)
        logger.info("%s", message)


def check(store: ArangoStore, *, edges: bool = True) -> Report:
    report = Report()
    raw = _raw_counts(store)
    _check_raw(raw, report)
    _check_nodes(store, raw, report)
    if edges:
        _check_edges(store, report)
    _check_views(store, report)
    return report


def _raw_counts(store: ArangoStore) -> dict[tuple[str, str], int]:
    aql = f"""
    FOR r IN {COLLECTION_RAW_SOURCES}
        COLLECT source = r.source, kind = r.kind WITH COUNT INTO n
        RETURN {{source, kind, n}}
    """
    return {(row["source"], row["kind"]): row["n"] for row in store.query(aql)}


def _check_raw(raw: dict[tuple[str, str], int], report: Report) -> None:
    for source, kinds in RAW_SOURCE_KINDS.items():
        for kind in kinds:
            count = raw.get((source, kind), 0)
            if count:
                report.note(f"raw {source}/{kind}: {count:,}")
            elif kind not in OPTIONAL_KINDS:
                report.problem(
                    f"raw {source}/{kind}: no records. Was it retrieved, and did the source "
                    "answer what was asked?"
                )


def _check_nodes(
    store: ArangoStore, raw: dict[tuple[str, str], int], report: Report
) -> None:
    for source, collection in NODES_OF_SOURCE.items():
        stored = sum(n for (s, _), n in raw.items() if s == source)
        if not stored:
            continue
        aql = f"""
        FOR d IN {collection}
            FILTER d.props.source == @source
            COLLECT WITH COUNT INTO n
            RETURN n
        """
        nodes = next(iter(store.query(aql, {"source": source})), 0)
        records = raw.get((source, RECORD_KIND[source]), 0)
        command = f"`lawgraph normalize {source.replace('_', '-')}`"
        if not nodes:
            report.problem(
                f"{source}: {stored:,} raw records and no node in {collection}. Run {command}."
            )
        elif nodes < records * NORMALIZED_SHARE:
            report.problem(
                f"{source}: {records:,} {RECORD_KIND[source]} records and {nodes:,} nodes in "
                f"{collection}: normalize is behind. Run {command}."
            )
        else:
            report.note(f"nodes of {source} in {collection}: {nodes:,}")


def _check_edges(store: ArangoStore, report: Report) -> None:
    aql = f"""
    FOR e IN {COLLECTION_EDGES}
        FILTER DOCUMENT(e._from) == null OR DOCUMENT(e._to) == null
        COLLECT relation = e.relation WITH COUNT INTO n
        RETURN {{relation, n}}
    """
    dangling = {row["relation"]: row["n"] for row in store.query(aql)}
    if dangling:
        detail = ", ".join(
            f"{relation}: {n:,}" for relation, n in sorted(dangling.items())
        )
        report.problem(f"edges to or from a node that does not exist: {detail}")
    else:
        report.note("edges: every edge has both its nodes")


def _check_views(store: ArangoStore, report: Report) -> None:
    for view, collection in SEARCH_VIEWS.items():
        aql = f"""
        LET indexed = FIRST(FOR d IN {view} COLLECT WITH COUNT INTO n RETURN n)
        LET stored = LENGTH({collection})
        RETURN {{indexed, stored}}
        """
        try:
            row = next(iter(store.query(aql)))
        except Exception as exc:
            report.problem(f"view {view}: cannot be read ({exc})")
            continue
        if row["indexed"] == row["stored"]:
            report.note(f"view {view}: {row['indexed']:,} documents")
        else:
            report.problem(
                f"view {view} holds {row['indexed']:,} of the {row['stored']:,} documents of "
                f"{collection}: it is out of sync. Drop the view; the next command "
                "creates and fills it again."
            )


def main(argv: list[str] | None = None) -> None:
    setup_logging()
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--skip-edges",
        action="store_true",
        help="Leave out the edge check (two lookups per edge: minutes on millions of edges).",
    )
    args = parser.parse_args(argv)
    report = check(ArangoStore(), edges=not args.skip_edges)
    if report.problems:
        logger.error("check: %d problem(s).", len(report.problems))
        sys.exit(1)
    logger.info("check: no problems.")

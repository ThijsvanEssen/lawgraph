"""``lawgraph check``: is the database what the pipelines should have made of the sources?

A step can end "successfully" and still leave nothing behind: a source that answers no records
for a parameter it does not understand, a normalize step that was never run, a search view
that lost its index when the server was killed. Nothing complains about that on its own; this
command does. Every check is one read-only query; a problem is an error of the command:

  raw      every raw kind of the registry holds records
  nodes    every source with raw records has nodes (normalize did run and wrote something)
  edges    no edge points to a node that does not exist
  views    every search view holds what its collection holds (``out of sync`` after a crash)
  derived  what a normalize step keeps for a semantic step is there on every node it is read from
  papers   the XML of Tweede Kamer papers that was retrieved has been read into their documents
  cases    cases name the dossier they belong to
  payloads the text payloads of raw records are in the payload store (a few of every kind)
  size     the database stays below the alert size (``LAWGRAPH_DB_SIZE_ALERT_GIB``, 70 GiB)
           and the server reports its license limit as not reached
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field

from lawgraph.config.constants import (
    COLLECTION_CASES,
    COLLECTION_DOCUMENTS,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    RAW_KIND_BWB_TOESTAND,
    RAW_KIND_BWB_TOESTAND_ALL,
    RAW_KIND_ECHR_JUDGMENT,
    RAW_KIND_EK_KAMERSTUK,
    RAW_KIND_EU_CELEX,
    RAW_KIND_RS_CONTENT,
    RAW_KIND_STB_AMVB,
    RAW_KIND_STCRT_REGELING,
    RAW_KIND_TK_KAMERSTUK_XML,
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
from lawgraph.config.settings import DB_SIZE_ALERT_GIB
from lawgraph.core.kamerstuk_xml import TEXT_SOURCE
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.db import ArangoStore
from lawgraph.db.queries import checks
from lawgraph.db.queries import raw as raw_queries
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
# Sources of which several records make one node, and how many nodes their records make:
# HUDOC holds a judgment once per language, and ``normalize echr`` keeps one of them.
NODES_OF_RECORDS = {SOURCE_ECHR: checks.count_echr_judgments_in_raw}
# Kinds that are only there after a manual command; their absence says nothing.
OPTIONAL_KINDS = {RAW_KIND_BWB_TOESTAND_ALL, RAW_KIND_TK_KAMERSTUK_XML}


@dataclass
class Report:
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def problem(self, message: str) -> None:
        self.problems.append(message)  # logged as the errors of the command

    def note(self, message: str) -> None:
        self.notes.append(message)
        logger.info("%s", message)


def check(store: ArangoStore, *, edges: bool = True) -> Report:
    report = Report()
    _check_size(store, report)
    raw = _raw_counts(store)
    _check_raw(raw, report)
    _check_payloads(store, raw, report)
    _check_nodes(store, raw, report)
    if edges:
        _check_edges(store, report)
    _check_views(store, report)
    _check_derived(store, report)
    _check_papers(store, raw, report)
    _check_cases(store, report)
    return report


GIB = 1024**3


def _check_size(store: ArangoStore, report: Report) -> None:
    """The size the server counts against its license, against the alert threshold; the
    largest collections say where it goes."""
    usage = store.disk_usage()
    used = int(usage.get("bytesUsed") or 0)
    limit = usage.get("bytesLimit")
    largest = sorted(store.collection_sizes().items(), key=lambda item: -item[1])[:3]
    line = (
        f"database size {used / GIB:.2f} GiB"
        + (f" of the {int(limit) / GIB:.0f} GiB the license allows" if limit else "")
        + f" (alert at {DB_SIZE_ALERT_GIB:g} GiB); largest: "
        + ", ".join(f"{name} {size / GIB:.2f} GiB" for name, size in largest)
    )
    status = usage.get("status", "good")
    if status != "good":
        report.problem(
            f"{line}. The server reports license status {status!r}: it turns read-only in "
            f"{usage.get('secondsUntilReadOnly', 0) / 3600:.0f} h and shuts down in "
            f"{usage.get('secondsUntilShutDown', 0) / 3600:.0f} h. Make it smaller now."
        )
    elif used >= DB_SIZE_ALERT_GIB * GIB:
        report.problem(f"{line}. Make it smaller before it reaches the limit.")
    else:
        report.note(line)


def _raw_counts(store: ArangoStore) -> dict[tuple[str, str], int]:
    rows = raw_queries.raw_counts(store)
    return {(row["source"], row["kind"]): row["n"] for row in rows}


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


# Records of each raw kind whose payload is looked for: a store that is not the one the
# payloads were written to misses all of them, a lost object is found by the next run.
PAYLOAD_SAMPLE = 3


def _check_payloads(
    store: ArangoStore, raw: dict[tuple[str, str], int], report: Report
) -> None:
    looked = missing = 0
    for source, kind in sorted(raw):
        for name in raw_queries.payload_refs_sample(
            store, source=source, kind=kind, sample=PAYLOAD_SAMPLE
        ):
            looked += 1
            if not store.payloads.exists(name):
                missing += 1
    where = store.payloads.location
    if missing:
        report.problem(
            f"payloads: {missing} of {looked} text payloads looked for are not in {where}. "
            "Is LAWGRAPH_PAYLOAD_STORE the store they were written to?"
        )
    elif looked:
        report.note(f"payloads: the {looked} looked for are in {where}")


def _check_nodes(
    store: ArangoStore, raw: dict[tuple[str, str], int], report: Report
) -> None:
    for source, collection in NODES_OF_SOURCE.items():
        stored = sum(n for (s, _), n in raw.items() if s == source)
        if not stored:
            continue
        nodes = checks.count_nodes_of_source(store, collection, source)
        records = raw.get((source, RECORD_KIND[source]), 0)
        counted = NODES_OF_RECORDS.get(source)
        expected = counted(store) if counted else records
        command = f"`lawgraph normalize {source.replace('_', '-')}`"
        if not nodes:
            report.problem(
                f"{source}: {stored:,} raw records and no node in {collection}. Run {command}."
            )
        elif nodes < expected * NORMALIZED_SHARE:
            stored_records = _records(records, expected, RECORD_KIND[source])
            report.problem(
                f"{source}: {stored_records} and {nodes:,} nodes in "
                f"{collection}: normalize is behind. Run {command}."
            )
        else:
            report.note(f"nodes of {source} in {collection}: {nodes:,}")


def _records(records: int, expected: int, kind: str) -> str:
    stored = f"{records:,} {kind} records"
    return stored if expected == records else f"{stored}, {expected:,} distinct,"


def _check_edges(store: ArangoStore, report: Report) -> None:
    dangling = {row["relation"]: row["n"] for row in checks.dangling_edges(store)}
    if dangling:
        detail = ", ".join(
            f"{relation}: {n:,}" for relation, n in sorted(dangling.items())
        )
        report.problem(f"edges to or from a node that does not exist: {detail}")
    else:
        report.note("edges: every edge has both its nodes")


def _check_views(store: ArangoStore, report: Report) -> None:
    for view, collection in SEARCH_VIEWS.items():
        try:
            row = checks.view_and_collection_size(store, view, collection)
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


def _check_derived(store: ArangoStore, report: Report) -> None:
    """``normalize bwb`` keeps the basis and the EU acts of a regulation on its node, and
    ``semantic bwb-grondslagen`` and ``semantic bwb-implements`` read only that: a regulation
    normalized before it was kept would give them nothing, and nothing would say so."""
    behind = checks.count_regulations_without_derived_props(store)
    if behind:
        report.problem(
            f"{behind:,} BWB regulations carry no `basis` / `celex_refs`: BASED_ON and "
            "IMPLEMENTS are read from them. Run `lawgraph normalize bwb`, then "
            "`lawgraph semantic all`."
        )
    else:
        report.note("derived: every BWB regulation carries its basis and EU acts")


def _check_papers(
    store: ArangoStore, raw: dict[tuple[str, str], int], report: Report
) -> None:
    """``retrieve tk-content`` keeps the XML of a paper; ``normalize tk-content`` writes its
    text and sections on the document. Without that step the documents keep no text, and the
    semantic steps read nothing of the papers."""
    stored = raw.get((SOURCE_TK, RAW_KIND_TK_KAMERSTUK_XML), 0)
    if not stored:
        return
    read = checks.count_documents_read_from(store, TEXT_SOURCE)
    if read < stored * NORMALIZED_SHARE:
        report.problem(
            f"tk: {stored:,} {RAW_KIND_TK_KAMERSTUK_XML} records and {read:,} documents with "
            "their text and sections: normalize is behind. Run `lawgraph normalize tk-content`, "
            "then `lawgraph semantic all`."
        )
    else:
        report.note(f"papers: {read:,} documents read from {stored:,} XML records")


def _check_cases(store: ArangoStore, report: Report) -> None:
    """A case reaches its dossier through the number it carries; when none of them carries
    one, the request for the cases did not ask for the dossier."""
    counts = checks.cases_by_named_dossier(store)
    total = sum(counts.values())
    if total and not counts.get(True):
        report.problem(
            f"none of the {total:,} cases names a dossier, so no case is part of one. "
            "Run `lawgraph retrieve tk` again for the window, then `normalize tk` and "
            "`normalize tk-dossiers`."
        )
    elif total:
        report.note(f"cases: {counts[True]:,} of {total:,} name a dossier")


def main(argv: list[str] | None = None) -> PipelineResult:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument(
        "--skip-edges",
        action="store_true",
        help="Leave out the edge check (two lookups per edge: minutes on millions of edges).",
    )
    args = parser.parse_args(argv)
    report = check(ArangoStore(), edges=not args.skip_edges)
    return PipelineResult(errors=report.problems)

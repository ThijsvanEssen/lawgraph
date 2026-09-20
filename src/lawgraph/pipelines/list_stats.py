"""``lawgraph semantic list-stats``: precompute list-endpoint sort and filter keys on nodes.

Persists the keys onto each document so ``/api/instruments``, ``/api/judgments``
and friends can sort and filter via persistent indexes instead of deriving the
value per row.

Fields written:

instruments
    props.jurisdiction   — 'nl' (bwb_id present) | 'eu' (celex present) | null
    props.article_count  — count of PART_OF edges pointing at it
    props.kind           — lower-cased copy of props.kind when present

judgments
    props.court_code     — uppercase ECLI court segment (e.g. 'HR', 'GHARN')
    props.tier           — coarse tier label ('hoge_raad' / 'gerechtshof' /
                           'rechtbank' / 'bijzonder')
    props.date_eff       — effective judgment date
    props.inbound_citation_count — count of inbound REFERS_TO edges

articles
    props.inbound_citation_count — count of inbound REFERS_TO / EXPLAINS edges

committees
    props.active_dossier_count — committees leading an activity about an open
                                 dossier

Idempotent: only writes when the computed value differs from what is already on
the document.
"""

from __future__ import annotations

import argparse
from typing import Any, cast

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_COMMITTEES,
    COLLECTION_DOSSIERS,
    COLLECTION_EDGES,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    RELATION_ABOUT,
    RELATION_EXPLAINS,
    RELATION_LED_BY,
    RELATION_PART_OF,
    RELATION_REFERS_TO,
)
from lawgraph.core.logging import get_logger
from lawgraph.core.models import PipelineResult
from lawgraph.db import ArangoStore
from lawgraph.pipelines.factory import run_step

logger = get_logger(__name__)

# Each entry below is one query body that selects the stale documents, plus a
# tail that either counts them (--dry-run) or writes the computed values.
_COUNT_TAIL = "    COLLECT WITH COUNT INTO n\n    RETURN n"


def _update_tail(collection: str, variable: str, assignments: str) -> str:
    return (
        f"    UPDATE {variable} WITH {{ props: {{{assignments}}} }}\n"
        f"    IN {collection} OPTIONS {{ mergeObjects: true }}\n"
        "    RETURN 1"
    )


_INSTRUMENTS_BODY = f"""
FOR inst IN {COLLECTION_INSTRUMENTS}
    LET jurisdiction = LOWER(
        inst.props.jurisdiction != null ? inst.props.jurisdiction :
        (inst.props.celex != null ? 'eu' :
         (inst.props.bwb_id != null ? 'nl' : null))
    )
    LET article_count = LENGTH(
        FOR e IN {COLLECTION_EDGES}
            FILTER e._to == inst._id AND e.relation == @part_of
            RETURN 1
    )
    LET kind = inst.props.kind != null ? LOWER(inst.props.kind) : null
    FILTER inst.props.jurisdiction != jurisdiction
        OR inst.props.article_count != article_count
        OR inst.props.kind != kind
"""

# Attributes are read one by one (``doc.props.ecli``), never ``LET props = doc.props``: that
# copies the whole props of every judgment, text and paragraphs included, into the query.
_JUDGMENTS_BODY = f"""
FOR doc IN {COLLECTION_JUDGMENTS}
    LET ecli = doc.props.ecli != null ? doc.props.ecli : doc._key
    LET ecli_parts = SPLIT(ecli, ':')
    LET court_code = LENGTH(ecli_parts) >= 3 ? UPPER(ecli_parts[2]) : null
    LET tier = (
        court_code == 'HR' ? 'hoge_raad' :
        (court_code != null AND STARTS_WITH(court_code, 'GH') ? 'gerechtshof' :
         (court_code != null AND STARTS_WITH(court_code, 'RB') ? 'rechtbank' :
          (court_code == null ? null : 'bijzonder')))
    )
    LET date_eff = (
        doc.props.judgment_metadata != null AND doc.props.judgment_metadata.date != null
            ? doc.props.judgment_metadata.date :
        (doc.props.meta != null AND doc.props.meta.date != null ? doc.props.meta.date :
         (doc.props.date != null ? doc.props.date : null))
    )
    LET inbound_cnt = LENGTH(
        FOR e IN {COLLECTION_EDGES}
            FILTER e._to == doc._id AND e.relation IN @inbound_rels
            FILTER STARTS_WITH(e._from, '{COLLECTION_JUDGMENTS}/')
            RETURN 1
    )
    FILTER doc.props.court_code != court_code
        OR doc.props.tier != tier
        OR doc.props.date_eff != date_eff
        OR doc.props.inbound_citation_count != inbound_cnt
"""

_ARTICLES_BODY = f"""
FOR art IN {COLLECTION_ARTICLES}
    LET inbound_cnt = LENGTH(
        FOR e IN {COLLECTION_EDGES}
            FILTER e._to == art._id AND e.relation IN @inbound_rels
            RETURN 1
    )
    FILTER art.props.inbound_citation_count != inbound_cnt
"""

_COMMITTEES_BODY = f"""
LET open_dossier_map = MERGE(
    FOR d IN {COLLECTION_DOSSIERS}
        FILTER d.props.closed == false
        RETURN {{ [d._id]: true }}
)
LET open_activity_map = MERGE(
    FOR e IN {COLLECTION_EDGES}
        FILTER e.relation == @about
        FILTER open_dossier_map[e._to] == true
        RETURN {{ [e._from]: true }}
)
LET counts = (
    FOR e IN {COLLECTION_EDGES}
        FILTER e.relation == @led_by
        FILTER open_activity_map[e._from] == true
        COLLECT committee = e._to WITH COUNT INTO cnt
        RETURN {{ id: committee, count: cnt }}
)
LET count_map = MERGE(FOR x IN counts RETURN {{ [x.id]: x.count }})
FOR doc IN {COLLECTION_COMMITTEES}
    LET active_dossier_count = count_map[doc._id] != null ? count_map[doc._id] : 0
    FILTER doc.props.active_dossier_count != active_dossier_count
"""


def _run(
    store: ArangoStore,
    body: str,
    tail: str,
    bind: dict[str, Any] | None,
    *,
    dry_run: bool,
) -> int:
    """Count stale documents (dry run) or update them; returns the number."""
    if dry_run:
        rows = list(store.query(body + _COUNT_TAIL, bind))
        return cast(int, rows[0]) if rows else 0
    return len(list(store.query(body + tail, bind)))


def _refresh_instruments(store: ArangoStore, *, dry_run: bool) -> int:
    return _run(
        store,
        _INSTRUMENTS_BODY,
        _update_tail(
            COLLECTION_INSTRUMENTS,
            "inst",
            "jurisdiction: jurisdiction, article_count: article_count, kind: kind",
        ),
        {"part_of": RELATION_PART_OF},
        dry_run=dry_run,
    )


def _refresh_judgments(store: ArangoStore, *, dry_run: bool) -> int:
    return _run(
        store,
        _JUDGMENTS_BODY,
        _update_tail(
            COLLECTION_JUDGMENTS,
            "doc",
            "court_code: court_code, tier: tier, date_eff: date_eff,"
            " inbound_citation_count: inbound_cnt",
        ),
        {"inbound_rels": [RELATION_REFERS_TO]},
        dry_run=dry_run,
    )


def _refresh_articles(store: ArangoStore, *, dry_run: bool) -> int:
    return _run(
        store,
        _ARTICLES_BODY,
        _update_tail(COLLECTION_ARTICLES, "art", "inbound_citation_count: inbound_cnt"),
        {"inbound_rels": [RELATION_REFERS_TO, RELATION_EXPLAINS]},
        dry_run=dry_run,
    )


def _refresh_committees(store: ArangoStore, *, dry_run: bool) -> int:
    return _run(
        store,
        _COMMITTEES_BODY,
        _update_tail(
            COLLECTION_COMMITTEES, "doc", "active_dossier_count: active_dossier_count"
        ),
        {"about": RELATION_ABOUT, "led_by": RELATION_LED_BY},
        dry_run=dry_run,
    )


_REFRESHERS = (
    ("instruments", _refresh_instruments),
    ("judgments", _refresh_judgments),
    ("committees", _refresh_committees),
    ("articles", _refresh_articles),
)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Precompute the list-endpoint sort and filter keys on instruments, "
            "judgments, articles and committees so those endpoints can sort and "
            "filter via persistent indexes."
        )
    )
    only_group = parser.add_mutually_exclusive_group()
    for name, _ in _REFRESHERS:
        only_group.add_argument(
            f"--{name}-only", action="store_true", help=f"Only update {name}."
        )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report how many docs would change; write nothing.",
    )
    args = parser.parse_args(argv)

    def run() -> PipelineResult:
        store = ArangoStore()
        selected = [name for name, _ in _REFRESHERS if getattr(args, f"{name}_only")]
        result = PipelineResult()
        for name, refresh in _REFRESHERS:
            if selected and name not in selected:
                continue
            count = refresh(store, dry_run=args.dry_run)
            if args.dry_run:
                logger.info("Would update %d %s.", count, name)
                result.skipped += count
            else:
                result.updated += count
        return result

    run_step("List stats", run)

"""The list keys ``lawgraph semantic graph-list-stats`` keeps on nodes: per collection one
query that selects the documents whose stored keys differ from what the graph gives, and either
counts them (a dry run) or writes the keys. Each ``refresh_*`` returns the number."""

from __future__ import annotations

import datetime as dt
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
    RELATION_SAME_AS,
)
from lawgraph.core.courts import COURT_BY_CODE, OTHER_COURT_BY_NAME, Court
from lawgraph.core.judgment_names import CURATED_NAMES
from lawgraph.core.judgments import KIND_OF_COURT_KIND
from lawgraph.db.counting import Store

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
    // its articles only: its annexes are PART_OF it too
    LET article_count = LENGTH(
        FOR e IN {COLLECTION_EDGES}
            FILTER e._to == inst._id AND e.relation == @part_of
            FILTER STARTS_WITH(e._from, '{COLLECTION_ARTICLES}/')
            RETURN 1
    )
    LET kind = inst.props.kind != null ? LOWER(inst.props.kind) : null
    // what refers to the law: to the law itself, and to each of its articles
    LET inbound_cnt = LENGTH(
        FOR e IN {COLLECTION_EDGES}
            FILTER e._to == inst._id AND e.relation == @refers_to
            RETURN 1
    ) + LENGTH(
        FOR p IN {COLLECTION_EDGES}
            FILTER p._to == inst._id AND p.relation == @part_of
            FOR e IN {COLLECTION_EDGES}
                FILTER e._to == p._from AND e.relation == @refers_to
                RETURN 1
    )
    FILTER inst.props.jurisdiction != jurisdiction
        OR inst.props.article_count != article_count
        OR inst.props.kind != kind
        OR inst.props.inbound_citation_count != inbound_cnt
"""

# Attributes are read one by one (``doc.props.ecli``), never ``LET props = doc.props``: that
# copies the whole props of every judgment, text and paragraphs included, into the query.
_JUDGMENTS_BODY = f"""
FOR doc IN {COLLECTION_JUDGMENTS}
    LET ecli = doc.props.ecli != null ? doc.props.ecli : doc._key
    LET ecli_parts = SPLIT(ecli, ':')
    LET court_code = LENGTH(ecli_parts) >= 3 ? UPPER(ecli_parts[2]) : null
    // ``core.courts.court_of``: the court of the code; of code XX the one its name names
    LET court = court_code == null ? null : (
        court_code == 'XX' AND HAS(@other_court_by_name, doc.props.court || '')
            ? @other_court_by_name[doc.props.court] : @court_by_code[court_code]
    )
    LET tier = court == null ? null : court.tier
    LET court_kind = court == null ? null : court.court_kind
    LET date_eff = (
        doc.props.judgment_metadata != null AND doc.props.judgment_metadata.date != null
            ? doc.props.judgment_metadata.date :
        (doc.props.meta != null AND doc.props.meta.date != null ? doc.props.meta.date :
         (doc.props.date != null ? doc.props.date : null))
    )
    // the judgments that cite it or a publication of the same decision it keeps (SAME_AS
    // to it), each once
    LET publications = APPEND([doc._id], (
        FOR s IN {COLLECTION_EDGES}
            FILTER s._to == doc._id AND s.relation == @same_as
            RETURN s._from
    ))
    LET inbound_cnt = COUNT_DISTINCT(
        FOR publication IN publications
            FOR e IN {COLLECTION_EDGES}
                FILTER e._to == publication AND e.relation IN @inbound_rels
                FILTER STARTS_WITH(e._from, '{COLLECTION_JUDGMENTS}/')
                RETURN e._from
    )
    // the judgments it cites
    LET outbound_cnt = LENGTH(
        FOR e IN {COLLECTION_EDGES}
            FILTER e._from == doc._id AND e.relation IN @inbound_rels
            FILTER STARTS_WITH(e._to, '{COLLECTION_JUDGMENTS}/')
            RETURN 1
    )
    // A loaded judgment has both from `normalize`; a stub from its ECLI: the kind of its
    // kind of court (``core.judgments.KIND_OF_COURT_KIND``), the names of
    // ``core.judgment_names``.
    LET decision_kind = doc.props.decision_kind != null ? doc.props.decision_kind
        : @kind_of_court_kind[court_kind]
    LET names = doc.props.stub == true ? @curated_names[UPPER(ecli)]
        : doc.props.names
    FILTER doc.props.court_code != court_code
        OR doc.props.tier != tier
        OR doc.props.court_kind != court_kind
        OR doc.props.date_eff != date_eff
        OR doc.props.inbound_citation_count != inbound_cnt
        OR doc.props.outbound_citation_count != outbound_cnt
        OR doc.props.decision_kind != decision_kind
        OR doc.props.names != names
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
        FILTER d.props.closed != true
        RETURN {{ [d._id]: true }}
)
LET open_activity_map = MERGE(
    FOR e IN {COLLECTION_EDGES}
        FILTER e.relation == @about
        FILTER open_dossier_map[e._to] == true
        COLLECT activity = e._from INTO dossier_ids = e._to
        RETURN {{ [activity]: dossier_ids }}
)
LET counts = (
    FOR e IN {COLLECTION_EDGES}
        FILTER e.relation == @led_by
        FILTER open_activity_map[e._from] != null
        FOR dossier_id IN open_activity_map[e._from]
            COLLECT committee = e._to INTO led = dossier_id
            RETURN {{ id: committee, count: COUNT_UNIQUE(led) }}
)
LET count_map = MERGE(FOR x IN counts RETURN {{ [x.id]: x.count }})
FOR doc IN {COLLECTION_COMMITTEES}
    LET dissolved = doc.props.ended_on != null AND doc.props.ended_on <= @today
    LET active_dossier_count = dissolved || count_map[doc._id] == null
        ? 0 : count_map[doc._id]
    FILTER doc.props.active_dossier_count != active_dossier_count
"""


def _run(
    store: Store,
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


def refresh_instruments(store: Store, *, dry_run: bool) -> int:
    return _run(
        store,
        _INSTRUMENTS_BODY,
        _update_tail(
            COLLECTION_INSTRUMENTS,
            "inst",
            "jurisdiction: jurisdiction, article_count: article_count, kind: kind,"
            " inbound_citation_count: inbound_cnt",
        ),
        {"part_of": RELATION_PART_OF, "refers_to": RELATION_REFERS_TO},
        dry_run=dry_run,
    )


def _tiers(courts: dict[str, Court]) -> dict[str, dict[str, str]]:
    return {k: {"tier": c.tier, "court_kind": c.court_kind} for k, c in courts.items()}


def refresh_judgments(store: Store, *, dry_run: bool) -> int:
    return _run(
        store,
        _JUDGMENTS_BODY,
        _update_tail(
            COLLECTION_JUDGMENTS,
            "doc",
            "court_code: court_code, tier: tier, court_kind: court_kind,"
            " date_eff: date_eff,"
            " inbound_citation_count: inbound_cnt,"
            " outbound_citation_count: outbound_cnt, decision_kind: decision_kind,"
            " names: names",
        ),
        {
            "inbound_rels": [RELATION_REFERS_TO],
            "same_as": RELATION_SAME_AS,
            "court_by_code": _tiers(COURT_BY_CODE),
            "other_court_by_name": _tiers(OTHER_COURT_BY_NAME),
            "kind_of_court_kind": KIND_OF_COURT_KIND,
            "curated_names": {e: list(n) for e, n in CURATED_NAMES.items()},
        },
        dry_run=dry_run,
    )


def refresh_articles(store: Store, *, dry_run: bool) -> int:
    return _run(
        store,
        _ARTICLES_BODY,
        _update_tail(COLLECTION_ARTICLES, "art", "inbound_citation_count: inbound_cnt"),
        {"inbound_rels": [RELATION_REFERS_TO, RELATION_EXPLAINS]},
        dry_run=dry_run,
    )


def refresh_committees(store: Store, *, dry_run: bool) -> int:
    return _run(
        store,
        _COMMITTEES_BODY,
        _update_tail(
            COLLECTION_COMMITTEES, "doc", "active_dossier_count: active_dossier_count"
        ),
        {
            "about": RELATION_ABOUT,
            "led_by": RELATION_LED_BY,
            "today": dt.date.today().isoformat(),
        },
        dry_run=dry_run,
    )

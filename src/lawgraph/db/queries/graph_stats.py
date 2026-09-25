"""The list keys ``lawgraph semantic graph-list-stats`` keeps on nodes: per collection one
query that selects the documents whose stored keys differ from what the graph gives, and either
counts them (a dry run) or writes the keys. Each ``refresh_*`` returns the number."""

from __future__ import annotations

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
from lawgraph.core.judgment_names import CURATED_NAMES
from lawgraph.core.judgments import (
    KIND_OF_TIER,
    PREFIX_LENGTHS,
    TIER_OF_COURT,
    TIER_OF_OTHER_COURT,
    TIER_OF_PREFIX,
)
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
    // ``core.judgments.court_tier``: the code, else its longest known prefix
    LET tier = court_code == null ? null : (
        court_code == 'XX' AND HAS(@tier_of_other_court, doc.props.court || '')
            ? @tier_of_other_court[doc.props.court] : NOT_NULL(
            @tier_of_court[court_code],
            {", ".join(f"@tier_of_prefix[LEFT(court_code, {n})]" for n in PREFIX_LENGTHS)}
        )
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
    // A loaded judgment has both from `normalize`; a stub from its ECLI: the kind of its
    // tier (``core.judgments.KIND_OF_TIER``), the names of ``core.judgment_names``.
    LET decision_kind = doc.props.decision_kind != null ? doc.props.decision_kind
        : @kind_of_tier[tier]
    LET names = doc.props.stub == true ? @curated_names[UPPER(ecli)]
        : doc.props.names
    FILTER doc.props.court_code != court_code
        OR doc.props.tier != tier
        OR doc.props.date_eff != date_eff
        OR doc.props.inbound_citation_count != inbound_cnt
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
            "jurisdiction: jurisdiction, article_count: article_count, kind: kind",
        ),
        {"part_of": RELATION_PART_OF},
        dry_run=dry_run,
    )


def refresh_judgments(store: Store, *, dry_run: bool) -> int:
    return _run(
        store,
        _JUDGMENTS_BODY,
        _update_tail(
            COLLECTION_JUDGMENTS,
            "doc",
            "court_code: court_code, tier: tier, date_eff: date_eff,"
            " inbound_citation_count: inbound_cnt, decision_kind: decision_kind,"
            " names: names",
        ),
        {
            "inbound_rels": [RELATION_REFERS_TO],
            "tier_of_court": TIER_OF_COURT,
            "tier_of_prefix": TIER_OF_PREFIX,
            "tier_of_other_court": TIER_OF_OTHER_COURT,
            "kind_of_tier": KIND_OF_TIER,
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
        {"about": RELATION_ABOUT, "led_by": RELATION_LED_BY},
        dry_run=dry_run,
    )

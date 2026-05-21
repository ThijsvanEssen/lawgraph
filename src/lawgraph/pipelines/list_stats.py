"""CLI: backfill precomputed stats on instruments and judgments.

Persists list-endpoint sort/filter keys onto each document so
``/api/instruments`` and ``/api/judgments`` can sort and filter via
persistent indexes instead of per-row inline derivation.

Fields written:

instruments
    props.jurisdiction   — 'nl' (bwb_id present) | 'eu' (celex present) | null
    props.article_count  — count of PART_OF_INSTRUMENT edges pointing at it
    props.kind           — lower-cased copy of props.kind when present

judgments
    props.court_code     — uppercase ECLI court segment (e.g. 'HR', 'GHARN')
    props.tier           — coarse tier label ('hoge_raad' / 'gerechtshof' /
                           'rechtbank' / 'bijzonder')
    props.date_eff       — effective judgment date
    props.inbound_citation_count — count of inbound CITES_JUDGMENT edges

Idempotent: only writes when the computed value differs from what's already
on the document. Safe to re-run; new docs created after this runs are
covered by the normalize pipelines (see pipelines/normalize/*).
"""

from __future__ import annotations

import argparse
from typing import cast

from lawgraph.config.constants import (
    RELATION_CITES_ARTICLE,
    RELATION_CITES_JUDGMENT,
    RELATION_EXPLAINS_ARTICLE,
    RELATION_LICHT_TOE,
    RELATION_PART_OF_INSTRUMENT,
)
from lawgraph.config.settings import COLLECTION_EDGES
from lawgraph.core.logging import get_logger
from lawgraph.db import ArangoStore

logger = get_logger(__name__)


_INSTRUMENTS_AQL = f"""
FOR inst IN instruments
    LET props = inst.props
    LET jurisdiction = LOWER(
        props.jurisdiction != null ? props.jurisdiction :
        (props.celex != null ? 'eu' :
         (props.bwb_id != null ? 'nl' : null))
    )
    LET article_count = LENGTH(
        FOR e IN {COLLECTION_EDGES}
            FILTER e._from == inst._id AND e.relation == @part_of
            RETURN 1
    )
    LET kind = props.kind != null ? LOWER(props.kind) : null
    LET needs_update = (
        props.jurisdiction != jurisdiction
        OR props.article_count != article_count
        OR props.kind != kind
    )
    FILTER needs_update
    UPDATE inst WITH {{
        props: {{
            jurisdiction: jurisdiction,
            article_count: article_count,
            kind: kind
        }}
    }} IN instruments OPTIONS {{ mergeObjects: true }}
    RETURN 1
"""


_JUDGMENTS_AQL = """
FOR doc IN judgments
    LET props = doc.props
    LET ecli = props.ecli != null ? props.ecli : doc._key
    LET ecli_parts = SPLIT(ecli, ':')
    LET court_code = LENGTH(ecli_parts) >= 3 ? UPPER(ecli_parts[2]) : null
    LET tier = (
        court_code == 'HR' ? 'hoge_raad' :
        (court_code != null AND STARTS_WITH(court_code, 'GH') ? 'gerechtshof' :
         (court_code != null AND STARTS_WITH(court_code, 'RB') ? 'rechtbank' :
          (court_code == null ? null : 'bijzonder')))
    )
    LET date_eff = (
        props.judgment_metadata != null AND props.judgment_metadata.date != null
            ? props.judgment_metadata.date :
        (props.meta != null AND props.meta.date != null ? props.meta.date :
         (props.date != null ? props.date : null))
    )
    LET inbound_cnt = LENGTH(
        FOR e IN edges
            FILTER e._to == doc._id AND e.relation IN @inbound_rels
            RETURN 1
    )
    LET needs_update = (
        props.court_code != court_code
        OR props.tier != tier
        OR props.date_eff != date_eff
        OR props.inbound_citation_count != inbound_cnt
    )
    FILTER needs_update
    UPDATE doc WITH {
        props: {
            court_code: court_code,
            tier: tier,
            date_eff: date_eff,
            inbound_citation_count: inbound_cnt
        }
    } IN judgments OPTIONS { mergeObjects: true }
    RETURN 1
"""


_ARTICLES_AQL = f"""
FOR art IN instrument_articles
    LET inbound_cnt = LENGTH(
        FOR e IN {COLLECTION_EDGES}
            FILTER e._to == art._id AND e.relation IN @inbound_rels
            RETURN 1
    )
    LET needs_update = art.props.inbound_citation_count != inbound_cnt
    FILTER needs_update
    UPDATE art WITH {{
        props: {{ inbound_citation_count: inbound_cnt }}
    }} IN instrument_articles OPTIONS {{ mergeObjects: true }}
    RETURN 1
"""


def _backfill_articles(store: ArangoStore, *, dry_run: bool) -> int:
    bind = {
        "inbound_rels": [
            RELATION_CITES_ARTICLE,
            RELATION_EXPLAINS_ARTICLE,
            RELATION_LICHT_TOE,
        ],
    }
    if dry_run:
        check_aql = f"""
        FOR art IN instrument_articles
            LET inbound_cnt = LENGTH(
                FOR e IN {COLLECTION_EDGES}
                    FILTER e._to == art._id AND e.relation IN @inbound_rels
                    RETURN 1
            )
            FILTER art.props.inbound_citation_count != inbound_cnt
            COLLECT WITH COUNT INTO n
            RETURN n
        """
        rows = list(store.query(check_aql, bind))
        return cast(int, rows[0]) if rows else 0
    updated = list(store.query(_ARTICLES_AQL, bind))
    return len(updated)


def _backfill_instruments(store: ArangoStore, *, dry_run: bool) -> int:
    if dry_run:
        check_aql = f"""
        FOR inst IN instruments
            LET props = inst.props
            LET jurisdiction = LOWER(
                props.jurisdiction != null ? props.jurisdiction :
                (props.celex != null ? 'eu' :
                 (props.bwb_id != null ? 'nl' : null))
            )
            LET article_count = LENGTH(
                FOR e IN {COLLECTION_EDGES}
                    FILTER e._from == inst._id AND e.relation == @part_of
                    RETURN 1
            )
            LET kind = props.kind != null ? LOWER(props.kind) : null
            FILTER props.jurisdiction != jurisdiction
                OR props.article_count != article_count
                OR props.kind != kind
            COLLECT WITH COUNT INTO n
            RETURN n
        """
        rows = list(store.query(check_aql, {"part_of": RELATION_PART_OF_INSTRUMENT}))
        return cast(int, rows[0]) if rows else 0

    updated = list(
        store.query(_INSTRUMENTS_AQL, {"part_of": RELATION_PART_OF_INSTRUMENT})
    )
    return len(updated)


_COMMISSIES_AQL = """
LET open_dossier_map = MERGE(
    FOR d IN kamerstukdossiers
        FILTER d.props.afgedaan == false
        RETURN { [d._id]: true }
)
LET open_activity_map = MERGE(
    FOR e IN edges
        FILTER e.relation == 'DEEL_VAN_DOSSIER'
        FILTER open_dossier_map[e._to] == true
        RETURN { [e._from]: true }
)
LET counts = (
    FOR e IN edges
        FILTER e.relation == 'BEHANDELD_DOOR'
        FILTER open_activity_map[e._from] == true
        COLLECT commissie = e._to WITH COUNT INTO cnt
        RETURN { id: commissie, count: cnt }
)
LET count_map = MERGE(FOR x IN counts RETURN { [x.id]: x.count })
FOR doc IN commissies
    LET want = count_map[doc._id] != null ? count_map[doc._id] : 0
    FILTER doc.props.active_dossier_count != want
    UPDATE doc WITH {
        props: { active_dossier_count: want }
    } IN commissies OPTIONS { mergeObjects: true }
    RETURN 1
"""


def _backfill_commissies(store: ArangoStore, *, dry_run: bool) -> int:
    if dry_run:
        check_aql = """
        LET open_dossier_map = MERGE(
            FOR d IN kamerstukdossiers
                FILTER d.props.afgedaan == false
                RETURN { [d._id]: true }
        )
        LET open_activity_map = MERGE(
            FOR e IN edges
                FILTER e.relation == 'DEEL_VAN_DOSSIER'
                FILTER open_dossier_map[e._to] == true
                RETURN { [e._from]: true }
        )
        LET counts = (
            FOR e IN edges
                FILTER e.relation == 'BEHANDELD_DOOR'
                FILTER open_activity_map[e._from] == true
                COLLECT commissie = e._to WITH COUNT INTO cnt
                RETURN { id: commissie, count: cnt }
        )
        LET count_map = MERGE(FOR x IN counts RETURN { [x.id]: x.count })
        FOR doc IN commissies
            LET want = count_map[doc._id] != null ? count_map[doc._id] : 0
            FILTER doc.props.active_dossier_count != want
            COLLECT WITH COUNT INTO n
            RETURN n
        """
        rows = list(store.query(check_aql))
        return cast(int, rows[0]) if rows else 0
    return len(list(store.query(_COMMISSIES_AQL)))


def _backfill_judgments(store: ArangoStore, *, dry_run: bool) -> int:
    bind = {"inbound_rels": [RELATION_CITES_JUDGMENT]}
    if dry_run:
        check_aql = """
        FOR doc IN judgments
            LET props = doc.props
            LET ecli = props.ecli != null ? props.ecli : doc._key
            LET ecli_parts = SPLIT(ecli, ':')
            LET court_code = LENGTH(ecli_parts) >= 3 ? UPPER(ecli_parts[2]) : null
            LET tier = (
                court_code == 'HR' ? 'hoge_raad' :
                (court_code != null AND STARTS_WITH(court_code, 'GH') ? 'gerechtshof' :
                 (court_code != null AND STARTS_WITH(court_code, 'RB') ? 'rechtbank' :
                  (court_code == null ? null : 'bijzonder')))
            )
            LET date_eff = (
                props.judgment_metadata != null AND props.judgment_metadata.date != null
                    ? props.judgment_metadata.date :
                (props.meta != null AND props.meta.date != null ? props.meta.date :
                 (props.date != null ? props.date : null))
            )
            LET inbound_cnt = LENGTH(
                FOR e IN edges
                    FILTER e._to == doc._id AND e.relation IN @inbound_rels
                    RETURN 1
            )
            FILTER props.court_code != court_code
                OR props.tier != tier
                OR props.date_eff != date_eff
                OR props.inbound_citation_count != inbound_cnt
            COLLECT WITH COUNT INTO n
            RETURN n
        """
        rows = list(store.query(check_aql, bind))
        return cast(int, rows[0]) if rows else 0

    updated = list(store.query(_JUDGMENTS_AQL, bind))
    return len(updated)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Backfill jurisdiction/article_count/tier/date_eff onto instruments "
            "and judgments so the list endpoints can sort and filter via "
            "persistent indexes."
        )
    )
    parser.add_argument(
        "--instruments-only", action="store_true", help="Only update instruments."
    )
    parser.add_argument(
        "--judgments-only", action="store_true", help="Only update judgments."
    )
    parser.add_argument(
        "--commissies-only", action="store_true", help="Only update commissies."
    )
    parser.add_argument(
        "--articles-only", action="store_true", help="Only update instrument_articles."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Report how many docs would change; write nothing.",
    )
    args = parser.parse_args(argv)

    store = ArangoStore()

    only_one = (
        args.instruments_only
        or args.judgments_only
        or args.commissies_only
        or args.articles_only
    )
    verb = "Would update" if args.dry_run else "Updated"

    if not only_one or args.instruments_only:
        n = _backfill_instruments(store, dry_run=args.dry_run)
        logger.info("%s %d instruments.", verb, n)

    if not only_one or args.judgments_only:
        n = _backfill_judgments(store, dry_run=args.dry_run)
        logger.info("%s %d judgments.", verb, n)

    if not only_one or args.commissies_only:
        n = _backfill_commissies(store, dry_run=args.dry_run)
        logger.info("%s %d commissies.", verb, n)

    if not only_one or args.articles_only:
        n = _backfill_articles(store, dry_run=args.dry_run)
        logger.info("%s %d instrument_articles.", verb, n)


if __name__ == "__main__":
    main()

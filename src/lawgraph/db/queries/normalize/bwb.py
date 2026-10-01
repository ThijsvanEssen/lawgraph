"""The graph reads and updates of the normalize phase for BWB: article identities and
versions, the places stored for them, and the short titles set in place."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ARTICLE_VERSIONS,
    COLLECTION_ARTICLES,
    COLLECTION_INSTRUMENT_VERSIONS,
    COLLECTION_INSTRUMENTS,
)
from lawgraph.db.counting import Store
from lawgraph.db.queries._aql import sorted_merge


def update_abbreviations(store: Store, rows: list[dict[str, Any]]) -> int:
    """Set ``short_title`` and ``aliases`` on the instruments of *rows* (``{key,
    short_title, aliases}``) where either differs; how many changed. A null or empty
    value removes the prop."""
    aql = f"""
        FOR row IN @rows
            FOR inst IN {COLLECTION_INSTRUMENTS}
                FILTER inst._key == row.key
                LET aliases = LENGTH(row.aliases) > 0 ? row.aliases : null
                FILTER inst.props.short_title != row.short_title
                    OR inst.props.aliases != aliases
                LET cleared = APPEND(
                    row.short_title == null ? ["short_title"] : [],
                    aliases == null ? ["aliases"] : []
                )
                LET props = UNSET(
                    MERGE(inst.props, {{ short_title: row.short_title, aliases: aliases }}),
                    cleared
                )
                UPDATE inst WITH {{ props: {sorted_merge("props", "{}")} }}
                IN {COLLECTION_INSTRUMENTS} OPTIONS {{ mergeObjects: false }}
                RETURN 1
        """
    return len(list(store.query(aql, {"rows": rows})))


_ARTICLES_AQL = f"""
FOR a IN {COLLECTION_ARTICLES}
    FILTER a.props.bwb_id IN @ids
    RETURN {{key: a._key, bwb_id: a.props.bwb_id, stam_id: a.props.stam_id}}
"""


_VERSIONS_AQL = f"""
FOR v IN {COLLECTION_ARTICLE_VERSIONS}
    FILTER v.props.bwb_id IN @ids
    RETURN {{
        key: v._key,
        bwb_id: v.props.bwb_id,
        stam_id: v.props.stam_id,
        number: v.props.article_number,
        label: v.props.label,
        valid_from: v.props.valid_from,
        valid_until: v.props.valid_until,
        current: v.props.current,
        last_seen: v.props.last_seen,
        effect: v.props.effect,
        digest: v.props.content_digest,
        position: v.props.position,
        text_start: SUBSTRING(v.props.text, 0, 60),
        title: v.props.instrument_citation_title
    }}
"""


def article_identities(store: Store, bwb_ids: list[str]) -> Iterator[dict[str, Any]]:
    """``{key, bwb_id, stam_id}`` of the articles of *bwb_ids*."""
    return store.query(_ARTICLES_AQL, {"ids": bwb_ids})


def article_versions(store: Store, bwb_ids: list[str]) -> Iterator[dict[str, Any]]:
    """The article versions of *bwb_ids*, with their validity and article number."""
    return store.query(_VERSIONS_AQL, {"ids": bwb_ids})


def stored_places(store: Store, bwb_id: str) -> Iterator[dict[str, Any]]:
    """``{key, breadcrumb, breadcrumb_changes}`` of the article versions of *bwb_id*, in
    their stored order (``position``)."""
    aql = f"""
    FOR v IN {COLLECTION_ARTICLE_VERSIONS}
        FILTER v.props.bwb_id == @id
        SORT v.props.position == null, v.props.position, v._key
        RETURN {{
            key: v._key,
            breadcrumb: v.props.breadcrumb,
            breadcrumb_changes: v.props.breadcrumb_changes
        }}
    """
    return store.query(aql, {"id": bwb_id})


def article_version_starts(store: Store, keys: list[str]) -> dict[str, str]:
    """``valid_from`` of the article versions of *keys* that exist, by key."""
    aql = f"""
    FOR v IN {COLLECTION_ARTICLE_VERSIONS}
        FILTER v._key IN @keys AND v.props.valid_from != null
        RETURN [v._key, v.props.valid_from]
    """
    return dict(store.query(aql, {"keys": keys}))


def toestand_starts(store: Store, bwb_ids: list[str]) -> dict[str, list[str]]:
    """The start dates of the toestanden of each of *bwb_ids*, oldest first."""
    aql = f"""
    FOR v IN {COLLECTION_INSTRUMENT_VERSIONS}
        FILTER v.props.bwb_id IN @ids
        // COLLECT sorts on the id; sorting on it first keeps the dates in order inside it.
        SORT v.props.bwb_id, v.props.valid_from, v._key
        COLLECT bwb_id = v.props.bwb_id INTO starts = v.props.valid_from
        RETURN {{ bwb_id, starts }}
    """
    return {
        row["bwb_id"]: [s for s in row["starts"] if s]
        for row in store.query(aql, {"ids": bwb_ids})
    }

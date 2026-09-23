"""Links of an instrument to EU acts and to international law: `IMPLEMENTS`, treaties, ECHR.

`IMPLEMENTS` is written between two instruments by `semantic bwb-implements`, from a
regulation to every EU act whose CELEX number its text names. The international links are
`REFERS_TO` edges: from articles of the instrument to a BWB treaty (`BWBV...`), an article
of it, or an instrument of another treaty, and from ECHR judgments (`semantic echr`) to the
instrument or to its articles. Nothing else in the graph links a Dutch text to a treaty:
Verdragenbank treaties and the articles of the ECHR Convention have no inbound link from a
Dutch article.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from lawgraph.config.constants import (
    BWB_TREATY_ID_PREFIX,
    COLLECTION_ARTICLES,
    COLLECTION_EDGES,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    ECHR_CONVENTION_ID,
    RELATION_IMPLEMENTS,
    RELATION_REFERS_TO,
    SOURCE_ECHR,
)
from lawgraph.core.models import make_node_key
from lawgraph.db import ArangoStore
from lawgraph.db.queries.instrument_scope import InstrumentScope

# The keys of the articles of a treaty: BWB treaties by their BWBV id, the ECHR Convention by
# its pseudo id. The prefix keeps the edges of a large statute from being looked up one by
# one; the kind of the instrument is what decides in the end.
_TREATY_ARTICLE_PREFIXES = [
    f"{COLLECTION_ARTICLES}/{make_node_key(BWB_TREATY_ID_PREFIX)}",
    f"{COLLECTION_ARTICLES}/{make_node_key(ECHR_CONVENTION_ID)}_",
]


@dataclass
class EuLinksData:
    """`IMPLEMENTS` rows (`{instrument, edge}`) in both directions, with absolute totals."""

    implements: list[dict[str, Any]]
    implements_total: int
    implemented_by: list[dict[str, Any]]
    implemented_by_total: int


@dataclass
class InternationalLinksData:
    """Treaty rows and ECHR judgment rows, each with its absolute total."""

    treaties: list[dict[str, Any]]
    treaties_total: int
    judgments: list[dict[str, Any]]
    judgments_total: int


# The edge, as far as the API answers it, and an article, in AQL.
_EDGE_OF_ROW = (
    "{ confidence: r.edge.confidence, source: r.edge.source, meta: r.edge.meta }"
)
_EDGE_OF_E = "{ confidence: e.confidence, source: e.source, meta: e.meta }"


def _article_ref(var: str) -> str:
    return (
        f"{{ id: {var}._id, key: {var}._key, article_number: {var}.props.article_number,"
        f" display_name: {var}.props.display_name }}"
    )


def get_eu_links(
    store: ArangoStore, instrument_id: str, *, limit: int = 500
) -> EuLinksData:
    """The `IMPLEMENTS` edges out of and into an instrument, one query.

    Each row is `{instrument, edge}`: the instrument at the other end and `{confidence,
    source, meta}` of the edge. Highest confidence first.
    """
    aql = f"""
    LET implements = (
        FOR e IN {COLLECTION_EDGES}
            FILTER e._from == @id AND e.relation == @relation
            LET other = DOCUMENT(e._to)
            FILTER other != null
            RETURN {{ instrument: other, edge: e }}
    )
    LET implemented_by = (
        FOR e IN {COLLECTION_EDGES}
            FILTER e._to == @id AND e.relation == @relation
            LET other = DOCUMENT(e._from)
            FILTER other != null
            RETURN {{ instrument: other, edge: e }}
    )
    RETURN {{
        implements_total: LENGTH(implements),
        implements: (
            FOR r IN implements
                SORT r.edge.confidence DESC, r.instrument._key ASC
                LIMIT @limit
                RETURN {{ instrument: r.instrument, edge: {_EDGE_OF_ROW} }}
        ),
        implemented_by_total: LENGTH(implemented_by),
        implemented_by: (
            FOR r IN implemented_by
                SORT r.edge.confidence DESC, r.instrument._key ASC
                LIMIT @limit
                RETURN {{ instrument: r.instrument, edge: {_EDGE_OF_ROW} }}
        )
    }}
    """
    rows = list(
        store.query(
            aql, {"id": instrument_id, "relation": RELATION_IMPLEMENTS, "limit": limit}
        )
    )
    row = rows[0] if rows else {}
    return EuLinksData(
        implements=list(row.get("implements") or []),
        implements_total=int(row.get("implements_total") or 0),
        implemented_by=list(row.get("implemented_by") or []),
        implemented_by_total=int(row.get("implemented_by_total") or 0),
    )


def get_international_links(
    store: ArangoStore,
    instrument_id: str,
    scope: InstrumentScope | None,
    *,
    limit: int = 500,
) -> InternationalLinksData:
    """Treaties the articles of an instrument refer to, ECHR judgments that refer to it.

    Treaty rows: `{instrument, own_article, counterpart_article, edge}`, from the
    `REFERS_TO` edges of the instrument's articles into a treaty (an instrument of kind
    `verdrag` or jurisdiction `int`, or one of its articles). Judgment rows: `{judgment,
    own_article, edge}`, from the `REFERS_TO` edges of ECHR judgments into the instrument or
    one of its articles. Most confident first; the totals are independent of `limit`.
    """
    article_ids = (
        f"""
        FOR a IN {COLLECTION_ARTICLES}
            FILTER a.props.{scope.prop} == @scope_value
            RETURN a._id
        """
        if scope
        else "RETURN null"
    )
    aql = f"""
    LET own_ids = ({article_ids})
    LET treaty_rows = (
        FOR e IN {COLLECTION_EDGES}
            FILTER e._from IN own_ids AND e.relation == @relation
            FILTER STARTS_WITH(e._to, '{COLLECTION_INSTRUMENTS}/')
                OR STARTS_WITH(e._to, @treaty_prefixes, 1)
            LET target = DOCUMENT(e._to)
            FILTER target != null
            LET is_article = STARTS_WITH(e._to, '{COLLECTION_ARTICLES}/')
            LET treaty = is_article
                ? FIRST(
                    FOR i IN {COLLECTION_INSTRUMENTS}
                        FILTER i.props.bwb_id != null AND i.props.bwb_id == target.props.bwb_id
                        LIMIT 1 RETURN i)
                : target
            FILTER treaty != null
            FILTER treaty.props.kind == 'verdrag' OR treaty.props.jurisdiction == 'int'
            LET own = DOCUMENT(e._from)
            RETURN {{
                instrument: treaty,
                own_article: {_article_ref("own")},
                counterpart_article: is_article ? {_article_ref("target")} : null,
                edge: {_EDGE_OF_E}
            }}
    )
    // Only the sort keys are read for every judgment; the page is read whole.
    LET judgment_edges = (
        FOR e IN {COLLECTION_EDGES}
            FILTER e._to IN APPEND(own_ids, [@instrument_id]) AND e.relation == @relation
            FILTER STARTS_WITH(e._from, '{COLLECTION_JUDGMENTS}/')
            LET j = DOCUMENT(e._from)
            FILTER j != null AND j.props.source == @echr
            RETURN {{ key: e._key, confidence: e.confidence, date: j.props.date }}
    )
    RETURN {{
        treaties_total: LENGTH(treaty_rows),
        treaties: (
            FOR r IN treaty_rows
                SORT r.edge.confidence DESC, r.instrument._key ASC, r.own_article.key ASC
                LIMIT @limit
                RETURN r
        ),
        judgments_total: LENGTH(judgment_edges),
        judgments: (
            FOR r IN judgment_edges
                SORT r.confidence DESC, r.date DESC, r.key ASC
                LIMIT @limit
                LET e = DOCUMENT(CONCAT('{COLLECTION_EDGES}/', r.key))
                LET j = DOCUMENT(e._from)
                LET target = DOCUMENT(e._to)
                RETURN {{
                    judgment: {{
                        _id: j._id,
                        _key: j._key,
                        props: {{ ecli: j.props.ecli, display_name: j.props.display_name }}
                    }},
                    own_article: STARTS_WITH(e._to, '{COLLECTION_ARTICLES}/')
                        ? {_article_ref("target")}
                        : null,
                    edge: {_EDGE_OF_E}
                }}
        )
    }}
    """
    bind: dict[str, Any] = {
        "instrument_id": instrument_id,
        "relation": RELATION_REFERS_TO,
        "treaty_prefixes": _TREATY_ARTICLE_PREFIXES,
        "echr": SOURCE_ECHR,
        "limit": limit,
    }
    if scope:
        bind["scope_value"] = scope.value
    rows = list(store.query(aql, bind))
    row = rows[0] if rows else {}
    return InternationalLinksData(
        treaties=list(row.get("treaties") or []),
        treaties_total=int(row.get("treaties_total") or 0),
        judgments=list(row.get("judgments") or []),
        judgments_total=int(row.get("judgments_total") or 0),
    )

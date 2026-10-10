"""Links of an instrument to EU acts and to international law: `IMPLEMENTS`, treaties, ECHR.

`IMPLEMENTS` is written between two instruments by `semantic bwb-implements`, from a
publication or regulation to an EU act it implements by an implementation source; the EU
acts a regulation's text names without implementing them are `REFERS_TO` edges of the same
step between the two instruments. The international links are
`REFERS_TO` edges: from articles of the instrument to a BWB treaty (`BWBV...`), an article
of it, or an instrument of another treaty, and from ECHR judgments (`semantic echr`) to the
instrument or to its articles; the ECHR Convention is the BWB treaty BWBV0001000. Nothing else
in the graph links a Dutch text to a treaty: Verdragenbank treaties have no inbound link from
a Dutch article.
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
    EDGE_SOURCE_BWB_IMPLEMENTS,
    RELATION_IMPLEMENTS,
    RELATION_REFERS_TO,
    SOURCE_ECHR,
)
from lawgraph.core.models import make_node_key
from lawgraph.db import GraphStore
from lawgraph.db.queries.instrument_scope import InstrumentScope
from lawgraph.db.schema import node_of

# The keys of the articles of a treaty: BWB treaties, the ECHR Convention among them, by their
# BWBV id. The prefix keeps the edges of a large statute from being looked up one by one; the
# kind of the instrument is what decides in the end.
_TREATY_ARTICLE_PREFIXES = [
    f"{COLLECTION_ARTICLES}/{make_node_key(BWB_TREATY_ID_PREFIX)}",
]


@dataclass
class EuLinksData:
    """`IMPLEMENTS` rows (`{instrument, edge}`) in both directions, and the `REFERS_TO` rows
    of the EU acts a regulation names (`mentions`, `mentioned_by`), with absolute totals."""

    implements: list[dict[str, Any]]
    implements_total: int
    implemented_by: list[dict[str, Any]]
    implemented_by_total: int
    mentions: list[dict[str, Any]]
    mentions_total: int
    mentioned_by: list[dict[str, Any]]
    mentioned_by_total: int


@dataclass
class InternationalLinksData:
    """Treaty rows and ECHR judgment rows, each with its absolute total."""

    treaties: list[dict[str, Any]]
    treaties_total: int
    judgments: list[dict[str, Any]]
    judgments_total: int


# The edge as far as the API answers it: of an `eu-links` row with its relation.
_EDGE_FIELDS = ("confidence", "source", "meta")


def _edge_json(e: str, *, relation: bool) -> str:
    fields = ("relation", *_EDGE_FIELDS) if relation else _EDGE_FIELDS
    pairs = ", ".join(f"'{f}', {e}.doc -> '{f}'" for f in fields)
    return f"json_build_object({pairs})"


def _node_json(n: str) -> str:
    """The document of node row *n*, as ``node_doc`` makes it."""
    return (
        f"json_build_object('_key', {n}.key, '_id', {n}.id, 'type', {n}.type,"
        f" 'labels', to_json({n}.labels), 'props', {n}.props)"
    )


def _article_ref(a: str) -> str:
    return (
        f"json_build_object('id', {a}.id, 'key', {a}.key,"
        f" 'article_number', {a}.props -> 'article_number',"
        f" 'display_name', {a}.props -> 'display_name')"
    )


def _eu_side(name: str, end: str, other: str, relation: str) -> str:
    """SQL of one side of `eu-links`, two columns: the rows of the edges of *relation*
    whose *end* is the instrument, with the instrument at their *other* end, highest
    confidence first (``name``), and how many there are (``name_total``)."""
    source = "AND e.source = %(source)s" if relation == "mentions" else ""
    rows = f"""
        FROM {COLLECTION_EDGES} e
        JOIN {COLLECTION_INSTRUMENTS} i ON i.id = e.{other}_id
        WHERE e.{end}_id = %(id)s AND e.relation = %({relation})s
          AND e.{other}_collection = '{COLLECTION_INSTRUMENTS}'
          {source}
    """
    return f"""
    (
        SELECT coalesce(json_agg(r.row ORDER BY r.n), '[]'::json)
        FROM (
            SELECT json_build_object(
                'instrument', {_node_json("i")},
                'edge', {_edge_json("e", relation=True)}
            ) AS row,
            row_number() OVER (
                ORDER BY e.confidence DESC NULLS LAST, i.key, e.key
            ) AS n
            {rows}
        ) r
        WHERE r.n <= %(limit)s
    ) AS {name},
    (SELECT count(*)::int {rows}) AS {name}_total
    """


def get_eu_links(
    store: GraphStore, instrument_id: str, *, limit: int = 500
) -> EuLinksData:
    """The `IMPLEMENTS` edges out of and into an instrument, and the `REFERS_TO` edges of
    `semantic bwb-implements` (the EU acts a regulation names), one query.

    Each row is `{instrument, edge}`: the instrument at the other end and `{relation,
    confidence, source, meta}` of the edge. Highest confidence first.
    """
    sides = (
        ("implements", "from", "to", "implements"),
        ("implemented_by", "to", "from", "implements"),
        ("mentions", "from", "to", "mentions"),
        ("mentioned_by", "to", "from", "mentions"),
    )
    columns = ",".join(_eu_side(*side) for side in sides)
    bind = {
        "id": instrument_id,
        "implements": RELATION_IMPLEMENTS,
        "mentions": RELATION_REFERS_TO,
        "source": EDGE_SOURCE_BWB_IMPLEMENTS,
        "limit": limit,
    }
    rows = list(store.query(f"SELECT {columns}", bind))
    row = rows[0] if rows else {}

    def rows_of(name: str) -> list[dict[str, Any]]:
        return list(row.get(name) or [])

    def total_of(name: str) -> int:
        return int(row.get(f"{name}_total") or 0)

    return EuLinksData(
        implements=rows_of("implements"),
        implements_total=total_of("implements"),
        implemented_by=rows_of("implemented_by"),
        implemented_by_total=total_of("implemented_by"),
        mentions=rows_of("mentions"),
        mentions_total=total_of("mentions"),
        mentioned_by=rows_of("mentioned_by"),
        mentioned_by_total=total_of("mentioned_by"),
    )


# ``own``: the articles of the instrument. ``treaty_rows``: their REFERS_TO edges into a
# treaty instrument, or into an article of one (whose instrument is the first by key with
# its ``bwb_id``). ``judgment_edges``: the REFERS_TO edges of ECHR judgments into the
# instrument or its articles, with only what sorts them; the page is read whole.
_INTERNATIONAL_SQL = f"""
WITH own AS (
    SELECT a.id FROM {COLLECTION_ARTICLES} a WHERE {{scope}}
),
treaty_rows AS (
    SELECT treaty.id AS treaty_id, treaty.key AS treaty_key, e.key AS edge_key,
           e.confidence, own_article.key AS own_key, target.key AS target_key,
           e.to_collection = '{COLLECTION_ARTICLES}' AS is_article,
           {_node_json("treaty")} AS instrument,
           {_article_ref("own_article")} AS own_article,
           CASE WHEN e.to_collection = '{COLLECTION_ARTICLES}'
               THEN {_article_ref("target")} END AS counterpart_article,
           {_edge_json("e", relation=False)} AS edge
    FROM {COLLECTION_EDGES} e
    JOIN {COLLECTION_ARTICLES} own_article ON own_article.id = e.from_id
    CROSS JOIN {node_of("e.to_id", "e.to_collection")} target
    CROSS JOIN LATERAL (
        SELECT i.id, i.key, i.type, i.labels, i.props, i.kind, i.jurisdiction
        FROM {COLLECTION_INSTRUMENTS} i
        WHERE CASE WHEN e.to_collection = '{COLLECTION_ARTICLES}'
            THEN i.bwb_id = lg_str(target.props -> 'bwb_id')
            ELSE i.id = target.id END
        ORDER BY i.key
        LIMIT 1
    ) treaty
    WHERE e.from_id IN (SELECT id FROM own) AND e.relation = %(relation)s
      AND (
          e.to_collection = '{COLLECTION_INSTRUMENTS}'
          OR EXISTS (
              SELECT 1 FROM unnest(%(treaty_prefixes)s::text[]) AS p(prefix)
              WHERE starts_with(e.to_id, p.prefix)
          )
      )
      AND (treaty.kind = 'verdrag' OR treaty.jurisdiction = 'int')
),
{{judgment_edges}}
SELECT
    (SELECT count(*)::int FROM treaty_rows) AS treaties_total,
    (
        SELECT coalesce(json_agg(json_build_object(
            'instrument', t.instrument,
            'own_article', t.own_article,
            'counterpart_article', t.counterpart_article,
            'edge', t.edge
        ) ORDER BY t.n), '[]'::json)
        FROM (
            -- The edge key only settles ties; the answer does not carry it.
            SELECT r.*, row_number() OVER (
                ORDER BY r.confidence DESC NULLS LAST, r.treaty_key, r.own_key,
                         CASE WHEN r.is_article THEN r.target_key END NULLS FIRST,
                         r.edge_key
            ) AS n
            FROM treaty_rows r
        ) t
        WHERE t.n <= %(limit)s
    ) AS treaties,
    (SELECT count(*)::int FROM judgment_edges) AS judgments_total,
    (
        SELECT coalesce(json_agg(json_build_object(
            'judgment', json_build_object(
                '_id', j.id,
                '_key', j.key,
                'props', json_build_object(
                    'ecli', j.pj_ecli, 'display_name', j.pj_display_name
                )
            ),
            'own_article', CASE WHEN e.to_collection = '{COLLECTION_ARTICLES}'
                THEN {_article_ref("target")} END,
            'edge', {_edge_json("e", relation=False)}
        ) ORDER BY page.n), '[]'::json)
        FROM (
            SELECT r.key, row_number() OVER (
                ORDER BY r.confidence DESC NULLS LAST, r.date DESC NULLS LAST, r.key
            ) AS n
            FROM judgment_edges r
        ) page
        JOIN {COLLECTION_EDGES} e ON e.key = page.key
        JOIN {COLLECTION_JUDGMENTS} j ON j.id = e.from_id
        LEFT JOIN {COLLECTION_ARTICLES} target ON target.id = e.to_id
        WHERE page.n <= %(limit)s
    ) AS judgments
"""


# The edges of ECHR judgments into the instrument or its articles. A law cited little: from
# its edges, each judgment read to keep those of the ECHR. A law cited much (the Awb: a
# million edges of Dutch judgments): from the ECHR judgments and their edges, whose number
# does not grow with the law (``ECHR_SIDE_FROM``).
_JUDGMENT_EDGES_BY_TARGET = f"""
judgment_edges AS (
    SELECT e.key, e.confidence, lg_str(j.props -> 'date') AS date
    FROM {COLLECTION_EDGES} e
    JOIN {COLLECTION_JUDGMENTS} j ON j.id = e.from_id
    WHERE e.to_id IN (SELECT id FROM own UNION ALL SELECT %(instrument_id)s)
      AND e.relation = %(relation)s
      AND e.from_collection = '{COLLECTION_JUDGMENTS}'
      AND j.source = %(echr)s
)"""
_JUDGMENT_EDGES_BY_ECHR = f"""
echr_edges AS MATERIALIZED (
    SELECT e.key, e.confidence, e.from_id, e.to_id
    FROM {COLLECTION_JUDGMENTS} j
    JOIN {COLLECTION_EDGES} e ON e.from_id = j.id AND e.relation = %(relation)s
        AND e.to_collection IN ('{COLLECTION_ARTICLES}', '{COLLECTION_INSTRUMENTS}')
    WHERE j.source = %(echr)s
),
judgment_edges AS (
    SELECT r.key, r.confidence, lg_str(j.props -> 'date') AS date
    FROM echr_edges r
    JOIN {COLLECTION_JUDGMENTS} j ON j.id = r.from_id
    WHERE r.to_id IN (SELECT id FROM own UNION ALL SELECT %(instrument_id)s)
)"""
# The citations of a law (``props.inbound_citation_count``: to it and its articles) from
# which its ECHR judgments are found from their side.
ECHR_SIDE_FROM = 2_000


def get_international_links(
    store: GraphStore,
    instrument_id: str,
    scope: InstrumentScope | None,
    *,
    limit: int = 500,
    cited: int | None = None,
) -> InternationalLinksData:
    """Treaties the articles of an instrument refer to, ECHR judgments that refer to it.

    Treaty rows: `{instrument, own_article, counterpart_article, edge}`, from the
    `REFERS_TO` edges of the instrument's articles into a treaty (an instrument of kind
    `verdrag` or jurisdiction `int`, or one of its articles). Judgment rows: `{judgment,
    own_article, edge}`, from the `REFERS_TO` edges of ECHR judgments into the instrument or
    one of its articles. Most confident first; the totals are independent of `limit`.
    *cited*: the citations of the instrument, which choose how its ECHR judgments are found.
    """
    # The scope is the indexed column of the articles: `bwb_id` or `celex`; without one
    # the instrument has no articles.
    condition = f"a.{scope.prop} = %(scope_value)s" if scope else "false"
    bind: dict[str, Any] = {
        "instrument_id": instrument_id,
        "relation": RELATION_REFERS_TO,
        "treaty_prefixes": _TREATY_ARTICLE_PREFIXES,
        "echr": SOURCE_ECHR,
        "limit": limit,
    }
    if scope:
        bind["scope_value"] = scope.value
    judgment_edges = (
        _JUDGMENT_EDGES_BY_ECHR
        if (cited or 0) >= ECHR_SIDE_FROM
        else _JUDGMENT_EDGES_BY_TARGET
    )
    sql = _INTERNATIONAL_SQL.replace("{scope}", condition).replace(
        "{judgment_edges}", judgment_edges.strip()
    )
    rows = list(store.query(sql, bind))
    row = rows[0] if rows else {}
    return InternationalLinksData(
        treaties=list(row.get("treaties") or []),
        treaties_total=int(row.get("treaties_total") or 0),
        judgments=list(row.get("judgments") or []),
        judgments_total=int(row.get("judgments_total") or 0),
    )

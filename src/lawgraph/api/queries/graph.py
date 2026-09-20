"""Graph layer query results and queries."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from lawgraph.config.constants import (
    COLLECTION_ARTICLES,
    COLLECTION_EDGES,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    RELATION_AMENDS,
    RELATION_EXPLAINS,
    RELATION_IMPLEMENTS,
    RELATION_PART_OF,
    RELATION_REFERS_TO,
)
from lawgraph.db import ArangoStore


@dataclass
class GraphEdge:
    from_id: str
    to_id: str
    relation_type: str
    weight: float | None = None
    confidence: float | None = None
    start: int | None = None
    end: int | None = None
    text: str | None = None


@dataclass
class InstrumentLayerData:
    instruments: list[dict[str, Any]]
    edges: list[GraphEdge]
    stats: dict[str, dict[str, Any]]
    metadata: dict[str, Any] | None = None


@dataclass
class JudgmentGraphData:
    judgments: list[dict[str, Any]]
    instruments: list[dict[str, Any]]
    edges: list[GraphEdge]
    metadata: dict[str, Any] | None = None


@dataclass
class GlobalGraphData:
    instruments: list[dict[str, Any]]
    articles: list[dict[str, Any]]
    judgments: list[dict[str, Any]]
    edges: list[GraphEdge]
    metadata: dict[str, Any] | None = None


def get_instrument_layer_graph(store: ArangoStore) -> InstrumentLayerData:
    """Return all non-stub instruments and aggregated inter-instrument reference edges.

    ``articles`` is scanned once into an ``id → bwb_id`` map and every edge
    endpoint is resolved against it, so no per-edge ``DOCUMENT()`` lookup is
    needed. Instruments are projected to the props the DTO reads — full docs
    (with long ``text`` / ``paragraphs``) never materialise on this path.
    """
    instruments: list[dict[str, Any]] = list(
        store.query(
            f"""
        FOR inst IN {COLLECTION_INSTRUMENTS}
            FILTER inst.props.stub != true OR inst.props.stub == null
            RETURN {{
                _id: inst._id,
                _key: inst._key,
                props: {{
                    bwb_id: inst.props.bwb_id,
                    celex: inst.props.celex,
                    display_name: inst.props.display_name,
                    citation_title: inst.props.citation_title,
                    title: inst.props.title,
                    short_title: inst.props.short_title,
                    shorthand: inst.props.shorthand,
                    jurisdiction: inst.props.jurisdiction,
                    stub: inst.props.stub
                }}
            }}
    """
        )
    )

    bwb_to_id: dict[str, str] = {}
    for inst in instruments:
        bwb = (inst.get("props") or {}).get("bwb_id")
        if bwb:
            bwb_to_id[bwb] = inst["_id"]

    # Aggregate article-level citations into instrument-level weighted edges.
    # The MERGE builds the article_id → bwb_id map upfront; the edge scan
    # then resolves both endpoints by dict lookup instead of DOCUMENT().
    rows: list[dict[str, Any]] = list(
        store.query(
            f"""
        LET id_to_bwb = MERGE(
            FOR a IN {COLLECTION_ARTICLES}
                FILTER a.props.bwb_id != null
                RETURN {{ [a._id]: a.props.bwb_id }}
        )
        FOR e IN {COLLECTION_EDGES}
            FILTER e.relation == "{RELATION_REFERS_TO}"
            LET fbwb = id_to_bwb[e._from]
            LET tbwb = id_to_bwb[e._to]
            FILTER fbwb != null AND tbwb != null AND fbwb != tbwb
            COLLECT fb = fbwb, tb = tbwb WITH COUNT INTO cnt
            FILTER cnt >= 2
            RETURN {{ from_bwb: fb, to_bwb: tb, weight: cnt }}
    """
        )
    )

    graph_edges: list[GraphEdge] = []
    for row in rows:
        fid = bwb_to_id.get(row["from_bwb"])
        tid = bwb_to_id.get(row["to_bwb"])
        if fid and tid:
            graph_edges.append(
                GraphEdge(
                    from_id=fid,
                    to_id=tid,
                    relation_type=RELATION_REFERS_TO,
                    weight=float(row["weight"]),
                )
            )

    # Direct instrument-to-instrument edges.
    direct: list[dict[str, Any]] = list(
        store.query(
            f"""
        FOR e IN {COLLECTION_EDGES}
            FILTER e.relation IN ["{RELATION_IMPLEMENTS}", "{RELATION_AMENDS}", "{RELATION_REFERS_TO}"]
            FILTER SPLIT(e._from, "/")[0] IN ["{COLLECTION_INSTRUMENTS}", "{COLLECTION_ARTICLES}"]
            FILTER SPLIT(e._to, "/")[0] == "{COLLECTION_INSTRUMENTS}"
            RETURN {{from_id: e._from, to_id: e._to, relation_type: e.relation}}
    """
        )
    )
    for de in direct:
        graph_edges.append(
            GraphEdge(
                from_id=de["from_id"],
                to_id=de["to_id"],
                relation_type=de["relation_type"],
            )
        )

    # Compute in-degree as citation_count per instrument.
    stats: dict[str, dict[str, Any]] = {
        inst["_id"]: {"citation_count": 0} for inst in instruments
    }
    for e in graph_edges:
        if e.to_id in stats:
            stats[e.to_id]["citation_count"] = stats[e.to_id]["citation_count"] + (
                int(e.weight or 1)
            )

    return InstrumentLayerData(instruments=instruments, edges=graph_edges, stats=stats)


def get_judgment_graph(
    store: ArangoStore,
    *,
    max_judgments: int = 1000,
    include_stubs: bool = False,
) -> JudgmentGraphData:
    """Return judgments, their cited instruments, and aggregated citation edges."""
    stub_filter = (
        "" if include_stubs else "FILTER j.props.stub != true OR j.props.stub == null"
    )
    # Lean judgment projection — DTO reads only id/key/ecli/display_name +
    # the heat/in-flux overlay fields. No text / paragraphs.
    judgments: list[dict[str, Any]] = list(
        store.query(
            f"""
        FOR j IN {COLLECTION_JUDGMENTS}
            {stub_filter}
            LIMIT @limit
            RETURN {{
                _id: j._id,
                _key: j._key,
                props: {{
                    ecli: j.props.ecli,
                    display_name: j.props.display_name,
                    date_eff: j.props.date_eff,
                    tier: j.props.tier,
                    court_code: j.props.court_code,
                    stub: j.props.stub,
                    inbound_citation_count: j.props.inbound_citation_count
                }}
            }}
    """,
            {"limit": max_judgments},
        )
    )

    if not judgments:
        return JudgmentGraphData(judgments=[], instruments=[], edges=[])

    judgment_ids = {j["_id"] for j in judgments}

    # Article-id → bwb_id map (one scan), then aggregate the judgment → article
    # references by dict lookup instead of a DOCUMENT() call per edge.
    rows = list(
        store.query(
            f"""
        LET id_to_bwb = MERGE(
            FOR a IN {COLLECTION_ARTICLES}
                FILTER a.props.bwb_id != null
                RETURN {{ [a._id]: a.props.bwb_id }}
        )
        FOR e IN {COLLECTION_EDGES}
            FILTER e.relation == "{RELATION_REFERS_TO}"
            FILTER STARTS_WITH(e._from, "{COLLECTION_JUDGMENTS}/")
            LET bwb = id_to_bwb[e._to]
            FILTER bwb != null
            RETURN {{ judgment_id: e._from, bwb_id: bwb }}
    """
        )
    )

    # Aggregate: (judgment_id, bwb_id) → count
    edge_weights: dict[tuple[str, str], int] = {}
    cited_bwb: set[str] = set()
    for row in rows:
        if row["judgment_id"] not in judgment_ids:
            continue
        key = (row["judgment_id"], row["bwb_id"])
        edge_weights[key] = edge_weights.get(key, 0) + 1
        cited_bwb.add(row["bwb_id"])

    instruments: list[dict[str, Any]] = []
    bwb_to_id: dict[str, str] = {}
    if cited_bwb:
        instruments = list(
            store.query(
                f"""
            FOR i IN {COLLECTION_INSTRUMENTS}
                FILTER i.props.bwb_id IN @bwb_ids
                RETURN i
        """,
                {"bwb_ids": list(cited_bwb)},
            )
        )
        bwb_to_id = {
            (i.get("props") or {}).get("bwb_id"): i["_id"]  # type: ignore[misc]
            for i in instruments
        }

    graph_edges: list[GraphEdge] = []
    for (jid, bwb), weight in edge_weights.items():
        iid = bwb_to_id.get(bwb)
        if iid:
            graph_edges.append(
                GraphEdge(
                    from_id=jid,
                    to_id=iid,
                    relation_type=RELATION_REFERS_TO,
                    weight=float(weight),
                )
            )

    return JudgmentGraphData(
        judgments=judgments, instruments=instruments, edges=graph_edges
    )


def get_global_graph(
    store: ArangoStore,
    *,
    include_judgments: bool = True,
    max_judgments: int = 500,
) -> GlobalGraphData:
    """Return a sample global graph: all instruments, stub articles, and optional judgments."""
    instruments: list[dict[str, Any]] = list(
        store.query(
            f"""
        FOR inst IN {COLLECTION_INSTRUMENTS}
            FILTER inst.props.stub != true OR inst.props.stub == null
            RETURN inst
    """
        )
    )
    articles: list[dict[str, Any]] = list(
        store.query(
            f"""
        FOR art IN {COLLECTION_ARTICLES}
            LIMIT 5000
            RETURN art
    """
        )
    )
    judgments: list[dict[str, Any]] = []
    if include_judgments:
        judgments = list(
            store.query(
                f"""
            FOR j IN {COLLECTION_JUDGMENTS}
                FILTER j.props.stub != true OR j.props.stub == null
                LIMIT @limit
                RETURN j
        """,
                {"limit": max_judgments},
            )
        )

    all_ids = list(
        {inst["_id"] for inst in instruments}
        | {art["_id"] for art in articles}
        | {j["_id"] for j in judgments}
    )

    # Push the all_ids filter into AQL so the DB uses the _from index and
    # never materialises edges whose endpoints are outside the loaded set.
    edges: list[dict[str, Any]] = list(
        store.query(
            f"""
        FOR e IN {COLLECTION_EDGES}
            FILTER e.relation IN [
                "{RELATION_REFERS_TO}", "{RELATION_EXPLAINS}",
                "{RELATION_PART_OF}", "{RELATION_IMPLEMENTS}", "{RELATION_AMENDS}"
            ]
            FILTER e._from IN @ids AND e._to IN @ids
            LIMIT 10000
            RETURN {{from_id: e._from, to_id: e._to, relation_type: e.relation, confidence: e.confidence}}
    """,
            {"ids": all_ids},
        )
    )

    graph_edges = [
        GraphEdge(
            from_id=e["from_id"],
            to_id=e["to_id"],
            relation_type=e["relation_type"],
            confidence=e.get("confidence"),
        )
        for e in edges
    ]

    return GlobalGraphData(
        instruments=instruments,
        articles=articles,
        judgments=judgments,
        edges=graph_edges,
    )

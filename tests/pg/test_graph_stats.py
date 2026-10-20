"""``semantic graph-list-stats`` on a real PostgreSQL: the keys it computes and writes."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.core.courts import COURT_BY_CODE
from lawgraph.core.judgment_kinds import KIND_OF_COURT_KIND
from lawgraph.db import GraphStore
from lawgraph.db.queries import _chunks as chunks
from lawgraph.db.queries import graph_stats
from tests.pg.plans import explain, plan_nodes, recorded


def _node(key: str, node_type: str, **props: Any) -> dict[str, Any]:
    return {"key": key, "type": node_type, "labels": [], "props": props}


def _edge(key: str, source: str, target: str, relation: str) -> dict[str, Any]:
    return {
        "key": key,
        "from_id": source,
        "to_id": target,
        "relation": relation,
        "source": "x",
        "status": "canoniek",
        "meta": {},
    }


def _props(store: GraphStore, collection: str, key: str) -> dict[str, Any]:
    doc = store.get_document(collection, key)
    assert doc is not None
    return doc["props"]


def test_instruments_count_their_articles_and_what_refers_to_them(
    store: GraphStore,
) -> None:
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            _node("w", "instrument", bwb_id="BWBR1", kind="Wet", uri=1),
            _node("x", "instrument"),
        ],
    )
    store.bulk_insert_or_update_edges(
        [
            _edge("1", "articles/a1", "instruments/w", "PART_OF"),
            _edge("2", "annexes/b1", "instruments/w", "PART_OF"),
            _edge("3", "judgments/j", "instruments/w", "REFERS_TO"),
            _edge("4", "judgments/j", "articles/a1", "REFERS_TO"),
            # PART_OF points article → instrument: one the other way is no article of it
            _edge("5", "instruments/w", "articles/a2", "PART_OF"),
        ]
    )
    assert graph_stats.refresh_instruments(store, dry_run=True) == 2
    assert graph_stats.refresh_instruments(store, dry_run=False) == 2
    assert graph_stats.refresh_instruments(store, dry_run=True) == 0
    props = _props(store, "instruments", "w")
    assert props == {
        "amending": False,
        "article_count": 1,
        "bwb_id": "BWBR1",
        "inbound_citation_count": 2,
        "jurisdiction": "nl",
        "kind": "wet",
        "uri": 1,
    }
    assert list(props) == sorted(props)  # the keys in order after an update
    assert _props(store, "instruments", "x")["jurisdiction"] == ""


def _regulation(
    store: GraphStore, bwb_id: str, articles: list[tuple[str, str]], **flags: Any
) -> None:
    """A BWB regulation and its articles (*articles*: number and text), each PART_OF it;
    *flags* go on every article (``repealed``)."""
    key = bwb_id.lower()
    store.bulk_insert_or_update_nodes(
        "instruments", [_node(key, "instrument", bwb_id=bwb_id)]
    )
    store.bulk_insert_or_update_nodes(
        "articles",
        [
            _node(
                f"{key}_{n}",
                "article",
                bwb_id=bwb_id,
                article_number=n,
                text=t,
                **flags,
            )
            for n, t in articles
        ],
    )
    store.bulk_insert_or_update_edges(
        [
            _edge(f"{key}_{n}", f"articles/{key}_{n}", f"instruments/{key}", "PART_OF")
            for n, _ in articles
        ]
    )


# What the BWB puts in place of an article that changed another regulation
# (``<redactie type="vervanging">``), and the articles a regulation has of its own.
_CHANGES = "Wijzigt het Delegatiebesluit 1993."
_OWN = "Deze regeling treedt in werking met ingang van 1 januari 1996."


def test_a_regulation_that_changes_others_is_amending(store: GraphStore) -> None:
    # numbered as a wijzigingsregeling (Artikel I, II, III) and changing another one
    # (Aanpassing Delegatiebesluit 1993, BWBR0007805): amending, though it keeps a
    # transitional article of its own
    _regulation(
        store,
        "BWBR0007805",
        [
            ("I", _CHANGES),
            ("II", "Voor de behandeling van verzoeken ..."),
            ("III", _OWN),
        ],
    )
    # numbered as a law, its articles mostly changes of other laws (Aanpassingswet AVG)
    _regulation(
        store,
        "BWBR0041233",
        [
            ("1.1", _CHANGES),
            ("1.2", "Wijzigt de Wet BRP."),
            ("1.3", _CHANGES),
            ("2", _OWN),
        ],
    )
    # a law of its own that changes another in a closing article: not amending
    _regulation(
        store,
        "BWBR0000003",
        [("1", "Begrippen."), ("2", "Regels."), ("3", "Meer regels."), ("4", _CHANGES)],
    )
    # Roman numbers, changing nothing (a treaty-like text, a regulation of its own)
    _regulation(store, "BWBR0000004", [("I", "Begrippen."), ("II", _OWN)])
    # repealed articles do not count
    _regulation(store, "BWBR0000005", [("I", _CHANGES)], repealed=True)
    # a treaty (BWBV) is never a wijzigingsregeling of the BWB
    _regulation(store, "BWBV0000006", [("I", _CHANGES)])
    graph_stats.refresh_instruments(store, dry_run=False)
    amending = {
        key: _props(store, "instruments", key)["amending"]
        for key in (
            "bwbr0007805",
            "bwbr0041233",
            "bwbr0000003",
            "bwbr0000004",
            "bwbr0000005",
            "bwbv0000006",
        )
    }
    assert amending == {
        "bwbr0007805": True,
        "bwbr0041233": True,
        "bwbr0000003": False,
        "bwbr0000004": False,
        "bwbr0000005": False,
        "bwbv0000006": False,
    }
    assert graph_stats.refresh_instruments(store, dry_run=True) == 0


def test_judgments_get_their_court_date_and_citations(store: GraphStore) -> None:
    hr = COURT_BY_CODE["HR"]
    store.bulk_insert_or_update_nodes(
        "judgments",
        [
            _node(
                "a", "judgment", ecli="ECLI:NL:HR:2020:1", meta={"date": "2020-01-01"}
            ),
            _node("b", "judgment", ecli="ECLI:NL:HR:2020:2", decision_kind="arrest"),
            _node("c", "judgment", ecli="ECLI:NL:HR:2020:3", stub=True),
        ],
    )
    store.bulk_insert_or_update_edges(
        [
            _edge("1", "judgments/b", "judgments/a", "REFERS_TO"),
            _edge("2", "judgments/c", "judgments/b", "REFERS_TO"),
            _edge("3", "judgments/b", "judgments/a", "SAME_AS"),
            _edge("4", "judgments/c", "judgments/a", "REFERS_TO"),
        ]
    )
    assert graph_stats.refresh_judgments(store, dry_run=False) == 3
    a = _props(store, "judgments", "a")
    assert (a["court_code"], a["tier"], a["court_kind"]) == (
        "HR",
        hr.tier,
        hr.court_kind,
    )
    assert a["date_eff"] == "2020-01-01"
    # b cites a, c cites a and c cites b, which is the same decision as a: b and c
    assert a["inbound_citation_count"] == 2
    assert a["decision_kind"] == KIND_OF_COURT_KIND.get(hr.court_kind)
    assert _props(store, "judgments", "b")["decision_kind"] == "arrest"
    assert _props(store, "judgments", "c")["outbound_citation_count"] == 2
    assert graph_stats.refresh_judgments(store, dry_run=True) == 0


def test_committees_count_the_open_dossiers_they_lead(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes(
        "committees",
        [_node("c1", "committee"), _node("c2", "committee", ended_on="2000-01-01")],
    )
    store.bulk_insert_or_update_nodes(
        "dossiers",
        [_node("1", "dossier", closed=False), _node("2", "dossier", closed=True)],
    )
    store.bulk_insert_or_update_edges(
        [
            _edge("1", "activities/a", "committees/c1", "LED_BY"),
            _edge("2", "activities/a", "dossiers/1", "ABOUT"),
            _edge("3", "activities/a", "dossiers/2", "ABOUT"),
            _edge("4", "activities/b", "committees/c1", "LED_BY"),
            _edge("5", "activities/b", "dossiers/1", "ABOUT"),
            _edge("6", "activities/a", "committees/c2", "LED_BY"),
        ]
    )
    assert graph_stats.refresh_committees(store, dry_run=False) == 2
    assert _props(store, "committees", "c1")["active_dossier_count"] == 1
    assert _props(store, "committees", "c2")["active_dossier_count"] == 0


def test_articles_count_what_refers_to_and_explains_them(store: GraphStore) -> None:
    store.bulk_insert_or_update_nodes("articles", [_node("a", "article")])
    store.bulk_insert_or_update_edges(
        [
            _edge("1", "judgments/j", "articles/a", "REFERS_TO"),
            _edge("2", "documents/d", "articles/a", "EXPLAINS"),
            _edge("3", "documents/d", "articles/a", "ABOUT"),
        ]
    )
    assert graph_stats.refresh_articles(store, dry_run=False) == 1
    assert _props(store, "articles", "a") == {"inbound_citation_count": 2}


def test_the_keys_are_written_a_chunk_at_a_time(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The differing documents are read, then written in chunks: every one is written once,
    the props they had stay, and a second run finds nothing to write."""
    monkeypatch.setattr(chunks, "CHUNK", 2)
    store.bulk_insert_or_update_nodes(
        "articles",
        [_node(f"a{n}", "article", heading=f"h{n}") for n in range(5)]
        + [_node("a5", "article", inbound_citation_count=0)],
    )
    store.bulk_insert_or_update_edges(
        [_edge(str(n), "judgments/j", f"articles/a{n}", "REFERS_TO") for n in range(5)]
    )
    writes: list[int] = []
    execute = store.execute

    def counted(*a: Any) -> Any:
        writes.append(1)
        return execute(*a)

    monkeypatch.setattr(store, "execute", counted)
    assert graph_stats.refresh_articles(store, dry_run=True) == 5
    assert graph_stats.refresh_articles(store, dry_run=False) == 5
    assert len(writes) == 3
    assert _props(store, "articles", "a4") == {
        "heading": "h4",
        "inbound_citation_count": 1,
    }
    assert _props(store, "articles", "a5") == {"inbound_citation_count": 0}
    assert graph_stats.refresh_articles(store, dry_run=True) == 0


def test_the_citations_of_a_judgment_are_counted_through_the_edge_index(
    store: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Per judgment the edges to it and to what is the same decision as it: one ``= ANY``
    of ids. An OR of the two read every edge for every judgment (the parity build stopped
    after ten minutes on 32,000 judgments)."""
    store.bulk_insert_or_update_nodes(
        "judgments", [_node("a", "judgment", ecli="ECLI:NL:HR:2020:1")]
    )
    # Citations as many as on the real graph: on a few edges the planner reads them whole
    # whatever the query.
    store.execute(
        "INSERT INTO judgments (id, type) SELECT 'judgments/filler_' || n, 'judgment'"
        " FROM generate_series(1, 2000) n"
    )
    store.execute(
        "INSERT INTO edges (key, from_id, to_id, doc)"
        " SELECT 'filler_' || n, 'judgments/filler_' || n % 1999,"
        " 'judgments/filler_' || n % 1997,"
        " json_build_object('relation', CASE WHEN n % 20 = 0 THEN 'SAME_AS'"
        " ELSE 'REFERS_TO' END)"
        " FROM generate_series(1, 20000) n"
    )
    store.vacuum_analyze()
    asked = recorded(store, monkeypatch)
    graph_stats.refresh_judgments(store, dry_run=True)
    statement, params, *_ = asked[-1]
    plan = explain(store, statement, params, disable=("seqscan",))
    scans = [
        (
            node["Node Type"],
            node.get("Relation Name", ""),
            node.get("Index Cond") or node.get("Recheck Cond") or "",
        )
        for node in plan_nodes(plan)
    ]
    # every read of the edges finds them by the judgment (``edges_to``, ``edges_from``)
    edges = [cond for _, table, cond in scans if table == "edges"]
    assert edges and all("to_id =" in c or "from_id =" in c for c in edges), scans

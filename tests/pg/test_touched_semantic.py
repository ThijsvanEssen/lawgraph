"""``--touched-since`` on a real PostgreSQL: ``semantic tk-dossier-outcomes`` and
``semantic tk-government`` come to the same for what a poll touched as a run over all, and
leave the rest alone."""

from __future__ import annotations

import datetime as dt
from typing import Any

from lawgraph.config.constants import (
    RAW_KIND_TK_BESLUIT,
    RAW_KIND_TK_DOCUMENT,
    RAW_KIND_TK_DOSSIER,
    RAW_KIND_TK_STEMMING,
    RAW_KIND_TK_TOEZEGGING,
    SOURCE_TK,
)
from lawgraph.core.tk_records import CAPACITY_GOVERNMENT, CAPACITY_MEMBER
from lawgraph.db import GraphStore, raw_source_doc
from lawgraph.db.queries.government import ROLE_FIRST_SIGNATORY
from lawgraph.pipelines.semantic import _touched as touched
from lawgraph.pipelines.semantic.tk_dossier_outcomes import (
    TKDossierOutcomesSemanticPipeline,
)
from lawgraph.pipelines.semantic.tk_government import TKGovernmentSemanticPipeline

NOW = dt.datetime.now(dt.timezone.utc)
SINCE = NOW - dt.timedelta(hours=2)
OLD = (NOW - dt.timedelta(days=30)).isoformat()
NEW = (NOW - dt.timedelta(minutes=5)).isoformat()

# GUIDs of the TK records; a node's key is the GUID with underscores
G_VOTE = "11111111-aaaa-4bbb-8ccc-000000000001"  # a Besluit fetched again: how it went
G_PAPER = (
    "22222222-aaaa-4bbb-8ccc-000000000002"  # a paper fetched again, through its case
)
G_BALLOT = "33333333-aaaa-4bbb-8ccc-000000000003"  # a Stemming fetched again
G_OLD = "44444444-aaaa-4bbb-8ccc-000000000004"  # fetched long ago
G_PROMISE = "55555555-aaaa-4bbb-8ccc-000000000005"  # a commitment fetched again
G_OLD_PROMISE = "66666666-aaaa-4bbb-8ccc-000000000006"
G_DOSSIER = "77777777-aaaa-4bbb-8ccc-000000000007"  # a new dossier, nothing in it yet


def _key(guid: str) -> str:
    return guid.replace("-", "_")


def _node(key: str, **props: Any) -> dict[str, Any]:
    return {"_key": key, "type": "t", "labels": [], "props": props}


def _edge(source: str, target: str, relation: str, at: str, **meta: Any) -> dict:
    return {
        "_key": f"{relation}-{source}-{target}".replace("/", "-"),
        "_from": source,
        "_to": target,
        "relation": relation,
        "source": "test",
        "meta": meta,
        "created_at": at,
    }


def _raw(kind: str, guid: str, at: str) -> dict[str, Any]:
    doc = raw_source_doc(
        source=SOURCE_TK, kind=kind, external_id=guid, payload_json={"Id": guid}
    )
    return {**doc, "fetched_at": at.replace("+00:00", "Z")}


def _fill(store: GraphStore) -> None:
    bill = {"primary_case_kind": "Wetgeving", "date": "2026-09-29"}
    store.bulk_insert_or_update_nodes(
        "dossiers",
        [_node(key, kind="Wetgeving") for key in ("100", "200", "300", "400", "500")]
        + [_node("600", external_id=G_DOSSIER)],
    )
    store.bulk_insert_or_update_nodes(
        "decisions",
        [
            _node(f"decision_{_key(G_VOTE)}", passed=False, **bill),
            _node(f"decision_{_key(G_OLD)}", passed=False, **bill),
            _node("ballot_target", passed=False, **bill),
        ],
    )
    store.bulk_insert_or_update_nodes(
        "instruments", [_node("stb_2026_1", date_published="2026-10-01")]
    )
    store.bulk_insert_or_update_nodes("cases", [_node("case_1", external_id="c1")])
    store.bulk_insert_or_update_nodes(
        "documents",
        [_node(_key(G_PAPER), date="2026-01-05", external_id=G_PAPER)],
    )
    store.bulk_insert_or_update_nodes("members", [_node("kamerlid", name="Kamerlid")])
    store.bulk_insert_or_update_nodes(
        "commitments",
        [
            _node(_key(G_PROMISE), minister_name="X", made_on="2026-10-01"),
            _node(_key(G_OLD_PROMISE), minister_name="Y", made_on="2026-01-01"),
        ],
    )
    store.bulk_insert_or_update_edges(
        [
            # 100: its Besluit was fetched again (the vote went, the edge is old)
            _edge(f"decisions/decision_{_key(G_VOTE)}", "dossiers/100", "ABOUT", OLD),
            # 200: a law was published in it (a new edge)
            _edge("instruments/stb_2026_1", "dossiers/200", "LEGISLATED_IN", NEW),
            # 300: a paper of its case was fetched again; a Kamerlid signed it first
            _edge(f"documents/{_key(G_PAPER)}", "cases/case_1", "PART_OF", OLD),
            _edge("cases/case_1", "dossiers/300", "PART_OF", OLD),
            _edge(
                "members/kamerlid",
                f"documents/{_key(G_PAPER)}",
                "AUTHORED",
                OLD,
                role=ROLE_FIRST_SIGNATORY,
                capacity=CAPACITY_MEMBER,
            ),
            # 400: a Stemming of its decision was fetched again (the VOTED edge is old)
            _edge("decisions/ballot_target", "dossiers/400", "ABOUT", OLD),
            _edge(
                "members/kamerlid",
                "decisions/ballot_target",
                "VOTED",
                OLD,
                record_ids=[G_BALLOT],
            ),
            # 500: nothing since long ago
            _edge(f"decisions/decision_{_key(G_OLD)}", "dossiers/500", "ABOUT", OLD),
        ]
    )
    store.insert_raw_sources(
        [
            _raw(RAW_KIND_TK_BESLUIT, G_VOTE, NEW),
            _raw(RAW_KIND_TK_DOCUMENT, G_PAPER, NEW),
            _raw(RAW_KIND_TK_STEMMING, G_BALLOT, NEW),
            _raw(RAW_KIND_TK_BESLUIT, G_OLD, OLD),
            _raw(RAW_KIND_TK_TOEZEGGING, G_PROMISE, NEW),
            _raw(RAW_KIND_TK_TOEZEGGING, G_OLD_PROMISE, OLD),
            _raw(RAW_KIND_TK_DOSSIER, G_DOSSIER, NEW),
        ]
    )


def _props(store: GraphStore, collection: str) -> dict[str, dict[str, Any]]:
    rows = store.query(
        f"SELECT json_build_object('k', key, 'p', props) FROM {collection}"
    )
    return {row["k"]: row["p"] for row in rows}


def test_the_touched_dossiers(store: GraphStore) -> None:
    _fill(store)
    assert touched.touched_dossiers(store, SINCE) == [
        "dossiers/100",
        "dossiers/200",
        "dossiers/300",
        "dossiers/400",
        "dossiers/600",
    ]
    assert touched.touched_commitments(store, SINCE) == [
        f"commitments/{_key(G_PROMISE)}"
    ]
    # a window that holds everything touches every dossier with a record or an edge
    long_ago = NOW - dt.timedelta(days=365)
    assert "dossiers/500" in touched.touched_dossiers(store, long_ago)


def test_outcomes_of_the_touched_dossiers_are_those_of_a_run_over_all(
    store: GraphStore,
) -> None:
    _fill(store)
    before = _props(store, "dossiers")
    TKDossierOutcomesSemanticPipeline(store=store).run(touched_since=SINCE)
    some = _props(store, "dossiers")
    assert some["500"] == before["500"]  # untouched: as it was
    TKDossierOutcomesSemanticPipeline(store=store).run()
    everything = _props(store, "dossiers")
    for key in ("100", "200", "300", "400", "600"):
        assert some[key] == everything[key], key
    assert everything["500"] != before["500"]  # a run over all did change it
    assert some["200"]["closed"] is True  # the law published in it


def test_government_of_the_touched_is_that_of_a_run_over_all(
    store: GraphStore,
) -> None:
    _fill(store)
    dossiers, commitments = _props(store, "dossiers"), _props(store, "commitments")
    TKGovernmentSemanticPipeline(store=store).run(touched_since=SINCE)
    some_dossiers = _props(store, "dossiers")
    some_commitments = _props(store, "commitments")
    assert some_dossiers["500"] == dossiers["500"]
    assert some_commitments[_key(G_OLD_PROMISE)] == commitments[_key(G_OLD_PROMISE)]
    TKGovernmentSemanticPipeline(store=store).run()
    all_dossiers = _props(store, "dossiers")
    all_commitments = _props(store, "commitments")
    for key in ("100", "200", "300", "400", "600"):
        assert some_dossiers[key] == all_dossiers[key], key
    assert some_commitments[_key(G_PROMISE)] == all_commitments[_key(G_PROMISE)]
    assert some_dossiers["300"]["initiative"] is True  # the Kamerlid signed first
    assert all_dossiers["500"] != dossiers["500"]
    assert all_commitments[_key(G_OLD_PROMISE)] != commitments[_key(G_OLD_PROMISE)]


def _signed(paper: str, at: str, capacity: str, function: str) -> dict:
    member = "kamerlid" if capacity == CAPACITY_MEMBER else "minister"
    return _edge(
        f"members/{member}",
        f"documents/{paper}",
        "AUTHORED",
        at,
        role=ROLE_FIRST_SIGNATORY,
        capacity=capacity,
        function=function,
    )


def test_a_window_reads_the_papers_of_a_dossier_only_when_its_first_may_change(
    store: GraphStore,
) -> None:
    """A paper signed later than the first, as almost every new one, leaves the dossier as
    it is; one dated before it has the dossier read again. Either way the same as a run
    over all."""
    store.bulk_insert_or_update_nodes(
        "dossiers", [_node("700", kind="Wetgeving"), _node("800", kind="Wetgeving")]
    )
    store.bulk_insert_or_update_nodes(
        "members", [_node("kamerlid", name="Kamerlid"), _node("minister", name="M")]
    )
    store.bulk_insert_or_update_nodes(
        "documents",
        [
            _node("p700", date="2026-01-05"),
            _node("p800", date="2026-03-01"),
            _node("later", date="2026-02-01"),
            _node("back", date="2026-01-01"),
        ],
    )
    store.bulk_insert_or_update_edges(
        [
            _edge("documents/p700", "dossiers/700", "PART_OF", OLD),
            _signed("p700", OLD, CAPACITY_MEMBER, "Tweede Kamerlid"),
            _edge("documents/p800", "dossiers/800", "PART_OF", OLD),
            _signed("p800", OLD, CAPACITY_MEMBER, "Tweede Kamerlid"),
        ]
    )
    TKGovernmentSemanticPipeline(store=store).run()
    assert _props(store, "dossiers")["700"]["first_signed"]["paper"] == "documents/p700"

    # the window: a later paper of 700, and a paper of 800 dated before its first
    store.bulk_insert_or_update_edges(
        [
            _edge("documents/later", "dossiers/700", "PART_OF", NEW),
            _signed("later", NEW, CAPACITY_GOVERNMENT, "minister van Financiën"),
            _edge("documents/back", "dossiers/800", "PART_OF", NEW),
            _signed("back", NEW, CAPACITY_GOVERNMENT, "minister van Financiën"),
        ]
    )
    from lawgraph.db.queries import government as government_queries

    assert government_queries.dossiers_whose_first_may_change(
        store, ["dossiers/700", "dossiers/800"], [], touched.edge_moment(SINCE)
    ) == ["dossiers/800"]

    TKGovernmentSemanticPipeline(store=store).run(touched_since=SINCE)
    some = _props(store, "dossiers")
    assert some["700"]["initiative"] is True  # the Kamerlid still signed first
    assert some["800"]["initiative"] is False  # the minister signed before
    assert some["800"]["first_signed"]["paper"] == "documents/back"
    TKGovernmentSemanticPipeline(store=store).run()
    everything = _props(store, "dossiers")
    for key in ("700", "800"):
        assert some[key] == everything[key], key

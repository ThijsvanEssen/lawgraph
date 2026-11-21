"""The full search answers the dossier it finds that plays now (``active_dossier``): one with
activity in the last 30 days, with its newest papers, the votes on its motions, its open
commitments and its law; none for a dossier that went quiet."""

from __future__ import annotations

import datetime as dt
from typing import Any

import pytest

from lawgraph.config.constants import (
    RELATION_ABOUT,
    RELATION_AMENDS,
    RELATION_PART_OF,
)
from lawgraph.core.time import dutch_today
from lawgraph.db import GraphStore, make_edge_doc, version_cache
from tests.databases import Api


def _day(days_ago: int) -> str:
    return (dutch_today() - dt.timedelta(days=days_ago)).isoformat()


def _nodes(store: GraphStore, collection: str, rows: list[dict[str, Any]]) -> None:
    store.bulk_insert_or_update_nodes(
        collection,
        [
            {
                "key": r.pop("key"),
                "type": collection[:-1],
                "labels": r.pop("labels", ["TK"]),
                "props": r,
            }
            for r in rows
        ],
    )


@pytest.fixture()
def store(store: GraphStore) -> GraphStore:
    version_cache.clear()
    _nodes(
        store,
        "dossiers",
        [
            {"key": "36611", "number": "36611", "label": "36611", "closed": False,
             "title": "Wijziging van de Wet inkomstenbelasting 2001 (Wijzigingswet "
                      "beëindiging salderingsregeling)", "last_activity": _day(3)},
            {"key": "34000", "number": "34000", "label": "34000", "closed": True,
             "title": "Evaluatie salderingsregeling", "last_activity": "2016-05-01"},
            {"key": "35000", "number": "35000", "label": "35000", "closed": False,
             "title": "Stikstof", "last_activity": _day(1)},
        ],
    )  # fmt: skip
    _nodes(
        store,
        "documents",
        [
            {"key": f"d{n}", "kind": "Brief regering", "title": f"Brief {n}",
             "date": _day(n), "dossier_numbers": ["36611"], "dossier_number": "36611"}
            for n in range(3, 8)
        ],
    )  # fmt: skip
    _nodes(
        store,
        "decisions",
        [
            {"key": "v_new", "kind": "Motie", "date": _day(5), "passed": True,
             "subject": "Motie over thuisbatterijen", "dossier_numbers": ["36611"],
             "tally": {"Voor": 80, "Tegen": 70}},
            {"key": "v_held", "kind": "Motie", "date": _day(4), "passed": None,
             "subject": "Motie aangehouden", "dossier_numbers": ["36611"],
             "decision_kind": "Stemmen - aangehouden"},
            {"key": "v_old", "kind": "Motie", "date": _day(90), "passed": False,
             "subject": "Oude motie", "dossier_numbers": ["36611"]},
            {"key": "v_bill", "kind": "Wetgeving", "date": _day(5), "passed": True,
             "subject": "Wetsvoorstel", "dossier_numbers": ["36611"]},
        ],
    )  # fmt: skip
    _nodes(
        store,
        "commitments",
        [
            {"key": "tz_open", "number": "TZ202611-001", "status": "Openstaand",
             "text": "De minister stuurt een brief.", "made_on": _day(6)},
            {"key": "tz_done", "number": "TZ202601-001", "status": "Afgedaan",
             "text": "Afgedaan.", "made_on": "2026-01-10"},
        ],
    )  # fmt: skip
    _nodes(
        store,
        "instruments",
        [
            {"key": "bwbr0002471", "bwb_id": "BWBR0002471", "jurisdiction": "nl",
             "display_name": "Wet inkomstenbelasting 2001", "labels": []},
        ],
    )  # fmt: skip
    edges = [
        *(
            make_edge_doc(f"documents/d{n}", "dossiers/36611", RELATION_PART_OF)
            for n in range(3, 8)
        ),
        make_edge_doc("commitments/tz_open", "dossiers/36611", RELATION_ABOUT),
        make_edge_doc("commitments/tz_done", "dossiers/36611", RELATION_ABOUT),
        make_edge_doc(
            "documents/d3",
            "instruments/bwbr0002471",
            RELATION_AMENDS,
            status="voorgesteld",
        ),
    ]
    store.bulk_insert_or_update_edges(edges)
    for table in ("dossiers", "documents", "decisions", "commitments"):
        store.execute(f"ANALYZE {table}")
    return store


def _search(api: Api, q: str, **params: Any) -> dict[str, Any]:
    return api.get_json("/api/search", q=q, **{"types": ["dossiers"], **params})


def test_a_dossier_with_recent_activity_is_the_answer(api: Api) -> None:
    active = _search(api, "salderingsregeling")["active_dossier"]
    assert active["number"] == "36611"
    assert active["path"] == "/dossiers/36611"
    assert active["short_title"] == "Wijzigingswet beëindiging salderingsregeling"
    assert active["last_activity"] == _day(3)
    assert [d["key"] for d in active["documents"]] == ["d3", "d4", "d5"]
    assert active["document_count"] == 5
    # the votes on its motions of the last 30 days, held ones too, newest first
    assert [m["key"] for m in active["motions"]] == ["v_held", "v_new"]
    assert active["motions"][1]["passed"] is True
    assert active["motions"][1]["tally"] == {"Voor": 80, "Tegen": 70}
    assert [c["key"] for c in active["commitments"]] == ["tz_open"]
    assert active["commitment_count"] == 1
    assert active["law"]["bwb_id"] == "BWBR0002471"
    assert active["law"]["relation"] == "amends"


def test_a_dossier_that_went_quiet_is_no_answer(api: Api) -> None:
    answer = _search(api, "evaluatie salderingsregeling")
    assert [h["key"] for h in answer["results"]["dossiers"]] == ["34000"]
    assert answer["active_dossier"] is None


def test_no_dossier_without_dossiers_while_typing_or_on_a_later_page(
    api: Api,
) -> None:
    assert _search(api, "salderingsregeling", types=["documents"])[
        "active_dossier"
    ] is None  # fmt: skip
    assert _search(api, "salderingsregeling", mode="live")["active_dossier"] is None
    assert _search(api, "salderingsregeling", offset=1)["active_dossier"] is None

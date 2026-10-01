from __future__ import annotations

import json

import pytest

from tests.parity import graph_equal
from tests.parity.graph_equal import (
    Choice,
    Part,
    _edge_text,
    _node_text,
    _pg_edge,
    _pg_node_text,
    compare_digests,
    digest,
    judge,
    report,
)


def test_a_node_reads_the_same_from_both_databases() -> None:
    arango = {
        "_key": "17050",
        "_id": "dossiers/17050",
        "_rev": "_x",
        "type": "dossier",
        "labels": ["TK"],
        "props": {"number": "17050", "closed": False, "order": 1.0},
    }
    pg = _pg_node_text(
        "dossier", ["TK"], '{"number": "17050", "closed": false, "order": 1}'
    )
    assert digest(_node_text(arango)) == digest(pg)


def test_an_edge_reads_the_same_from_both_databases_without_its_time() -> None:
    arango = {
        "_key": "k",
        "_id": "edges/k",
        "_from": "cases/a",
        "_to": "dossiers/1",
        "_rev": "_x",
        "relation": "PART_OF",
        "source": "tk-dossiers",
        "created_at": "2026-10-01T00:32:03+00:00",
        "meta": {},
    }
    doc = json.dumps(
        {
            "relation": "PART_OF",
            "source": "tk-dossiers",
            "created_at": "2026-10-01T12:00:00+00:00",
            "meta": {},
        }
    )
    relation, key, text = _pg_edge("k", "cases/a", "dossiers/1", doc)
    assert (relation, key) == ("PART_OF", "k")
    assert digest(_edge_text(arango)) == digest(text)


def test_the_order_of_the_keys_is_a_difference() -> None:
    assert digest('{"a": 1, "b": 2}') != digest('{"b": 2, "a": 1}')
    assert digest('{"a": 1}') == digest('{"a": 1.0}')  # D6


def test_the_digests_name_the_ids_on_one_side_and_the_ones_that_differ() -> None:
    assert compare_digests(
        {"x": "1", "y": "2", "z": "3"}, {"y": "2", "z": "4", "w": "5"}
    ) == (
        ["x"],
        ["w"],
        ["z"],
    )


def test_a_known_choice_is_counted_apart_and_the_rest_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    choice = Choice(
        "first-dossier",
        "the first dossier by key where the AQL had no SORT",
        lambda part, where, a, b: part == "edges/PART_OF" and "_to" in where,
    )
    monkeypatch.setattr(graph_equal, "KNOWN_CHOICES", [choice])
    result = Part("edges/PART_OF")
    judge(
        result,
        [
            ("k1", '{"_from": "a", "_to": "d/1"}', '{"_from": "a", "_to": "d/2"}'),
            ("k2", '{"_from": "a", "_to": "d/1"}', None),
            ("k3", '{"_from": "a", "n": 1}', '{"_from": "a", "n": 1.0}'),
        ],
    )
    assert result.choices == {"first-dossier": 1}
    assert result.fail_count == 1
    assert result.fails == ["k2 only in ArangoDB"]
    same, text = report([result, Part("articles", 3, 3)])
    assert not same
    assert "FAIL   edges/PART_OF" in text
    assert "CHOICE first-dossier: 1" in text
    assert text.endswith("2 parts: 1 FAIL, 0 CHOICE, 1 OK")


def test_an_edge_s_own_fields_are_compared_in_any_order_its_meta_in_order() -> None:
    arango = {
        "_key": "k",
        "_from": "a",
        "_to": "b",
        "relation": "REFERS_TO",
        "confidence": 1,
        "meta": {"x": 1, "y": 2},
    }
    same = _pg_edge(
        "k",
        "a",
        "b",
        '{"confidence": 1, "relation": "REFERS_TO", "meta": {"x": 1, "y": 2}}',
    )
    other = _pg_edge(
        "k",
        "a",
        "b",
        '{"relation": "REFERS_TO", "confidence": 1, "meta": {"y": 2, "x": 1}}',
    )
    assert digest(_edge_text(arango)) == digest(same[2])
    assert digest(_edge_text(arango)) != digest(other[2])

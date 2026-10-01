"""The comparison of the parity harness is strict where the contract is, and only there."""

from __future__ import annotations

import json
from typing import Any

from tests.parity.catalogue import Pools, Request, _resolve, fill
from tests.parity.compare import compare, first_difference, parse, search_agreement


def _answer(body: Any, status: int = 200, **headers: str) -> dict[str, Any]:
    text = body if isinstance(body, str) else json.dumps(body)
    return {
        "status": status,
        "headers": {
            "content-type": "application/json",
            "cache-control": "max-age=60",
            **headers,
        },
        "body": text,
    }


def test_key_order_is_a_difference() -> None:
    found = first_difference(
        parse('{"voor": 1, "tegen": 2}'), parse('{"tegen": 2, "voor": 1}')
    )
    assert found == ("$", "keys ['voor', 'tegen'] != ['tegen', 'voor']")


def test_array_order_and_nested_values_are_differences() -> None:
    assert first_difference(parse("[1, 2]"), parse("[2, 1]")) == ("$[0]", "1 != 2")
    found = first_difference(parse('{"a": {"b": [null]}}'), parse('{"a": {"b": [""]}}'))
    assert found == ("$.a.b[0]", "None != ''")


def test_one_and_one_point_zero_are_equal_but_true_is_not_one() -> None:
    assert first_difference(parse("[1, 2.5]"), parse("[1.0, 2.5]")) is None
    assert first_difference(parse("[true]"), parse("[1]")) is not None


def test_status_headers_and_etag_form() -> None:
    same = compare(
        "/api/x",
        {},
        _answer([1], etag='W/"0.72.0-123"'),
        _answer([1], etag='W/"0.72.0-9"'),
    )
    assert same.same
    other_form = compare(
        "/api/x", {}, _answer([1], etag='W/"0.72.0-1"'), _answer([1], etag='"x"')
    )
    assert not other_form.same and other_form.where == "headers"
    assert (
        compare("/api/x", {}, _answer([1]), _answer([1], status=404)).where == "status"
    )
    no_cache = _answer([1])
    no_cache["headers"]["cache-control"] = "no-store"
    assert compare("/api/x", {}, _answer([1]), no_cache).where == "headers"


def test_atom_is_compared_after_c14n() -> None:
    atom = {"content-type": "application/atom+xml", "cache-control": "max-age=60"}
    a = {"status": 200, "headers": atom, "body": '<feed a="1" b="2"><id>x</id></feed>'}
    b = {
        "status": 200,
        "headers": atom,
        "body": "<feed b='2' a='1'>\n  <id>x</id>\n</feed>",
    }
    assert compare("/api/feed.atom", {}, a, b).same


def test_search_answers_that_differ_in_their_hits_only_are_d3() -> None:
    hits = [{"id": "articles/a", "score": 0.5}, {"id": "articles/b", "score": 0.4}]
    golden = {"q": "wet", "results": {"articles": hits}}
    other = {"q": "wet", "results": {"articles": hits[::-1]}}
    result = compare("/api/search", {"q": "wet"}, _answer(golden), _answer(other))
    assert not result.same and result.allowed == "D3"
    fewer = {"q": "wet", "results": {"articles": hits[:1]}}
    result = compare("/api/search", {"q": "wet"}, _answer(golden), _answer(fewer))
    assert result.allowed == "D3"
    agreement = search_agreement(parse(json.dumps(golden)), parse(json.dumps(fewer)))
    assert agreement == [(True, 0.5)]
    other_query = {"q": "recht", "results": {"articles": hits}}
    result = compare("/api/search", {}, _answer(golden), _answer(other_query))
    assert result.allowed == ""


def test_a_capped_neighbourhood_is_d9_and_an_uncapped_one_is_strict() -> None:
    def hood(*nodes: str) -> dict[str, Any]:
        return {
            "focal_id": "dossiers/1",
            "nodes": [{"id": n} for n in nodes],
            "edges": [],
        }

    path = "/api/nodes/dossiers/1/neighborhood"
    capped = compare(
        path, {"cap": "2"}, _answer(hood("f", "a", "b")), _answer(hood("f", "a", "c"))
    )
    assert capped.allowed == "D9"
    strict = compare(
        path, {"cap": "5"}, _answer(hood("f", "a", "b")), _answer(hood("f", "a", "c"))
    )
    assert strict.allowed == ""


def test_catalogue_helpers() -> None:
    pools = Pools()
    for n in range(50):
        pools.add("ecli", f"ECLI:NL:HR:2020:{n}")
    assert (
        pools.sample("ecli") == pools.sample("ecli") and len(pools.sample("ecli")) == 20
    )
    assert fill("/api/judgments/{ecli}", {"ecli": "ECLI:NL:HR:2020:1"}) == (
        "/api/judgments/ECLI%3ANL%3AHR%3A2020%3A1"
    )
    request = Request("/api/search", (("q", "art. 1"),), "search")
    assert Request.from_json(request.as_json()) == request
    assert request.url == "/api/search?q=art.+1"
    schemas = {"Tier": {"enum": ["hoge_raad"], "type": "string"}}
    nullable = {"anyOf": [{"$ref": "#/components/schemas/Tier"}, {"type": "null"}]}
    assert _resolve(nullable, schemas)["enum"] == ["hoge_raad"]

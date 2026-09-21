"""What a client reads from ``/openapi.json``: every route described, typed and, when it
writes, marked with the key it asks for."""

from __future__ import annotations

from typing import Any

import pytest

from lawgraph.api.app import app

SPEC = app.openapi()
OPERATIONS = [
    (method.upper(), path, operation)
    for path, operations in SPEC["paths"].items()
    for method, operation in operations.items()
]
WRITING = {"POST", "PUT", "PATCH", "DELETE"}


def _answer_schema(operation: dict[str, Any]) -> dict[str, Any] | None:
    """The JSON schema of the 2xx answer; ``None`` for an answer without a body (204)."""
    for status in ("200", "201"):
        content = operation["responses"].get(status, {}).get("content")
        if content:
            return content["application/json"].get("schema") or {}
    return None


@pytest.mark.parametrize(("method", "path", "operation"), OPERATIONS)
def test_every_route_is_described_and_says_what_it_answers(
    method: str, path: str, operation: dict[str, Any]
) -> None:
    assert operation.get("summary") and operation.get("tags"), f"{method} {path}"
    schema = _answer_schema(operation)
    if schema is not None:
        described = "$ref" in schema or schema.get("items") or schema.get("properties")
        a_typed_map = isinstance(schema.get("additionalProperties"), dict)
        assert described or a_typed_map, f"{method} {path}"


def test_a_route_that_writes_names_its_key_in_the_schema() -> None:
    schemes = SPEC["components"]["securitySchemes"]
    assert {s["name"] for s in schemes.values()} == {"X-Write-Key", "X-Curation-Key"}
    assert all(s["type"] == "apiKey" and s["in"] == "header" for s in schemes.values())
    for method, path, operation in OPERATIONS:
        assert bool(operation.get("security")) == (method in WRITING), (
            f"{method} {path}"
        )


def _parameters(path: str) -> set[str]:
    return {
        p["name"]
        for p in SPEC["paths"][path]["get"].get("parameters", [])
        if p["in"] == "query"
    }


def test_the_node_routes_declare_their_filters_and_the_edge_of_a_neighbor() -> None:
    filters = {"relations", "node_types", "direction", "status"}
    node = "/api/nodes/{collection}/{key}"
    assert _parameters(node) == filters | {"limit", "offset"}
    assert _parameters(f"{node}/facets") == filters
    assert _parameters(f"{node}/neighborhood") == filters | {"depth", "cap"}

    schemas = SPEC["components"]["schemas"]
    assert {"edge_id", "status", "meta", "confidence"} <= set(
        schemas["NeighborDTO"]["properties"]
    )
    assert set(schemas["NeighborBucketDTO"]["properties"]) == {
        "relation",
        "direction",
        "collection",
        "type",
        "total",
        "next_offset",
        "items",
    }
    assert set(schemas["NodeFacetDTO"]["properties"]) == {
        "relation",
        "direction",
        "collection",
        "type",
        "count",
    }


def test_the_graph_routes_that_can_be_narrowed_say_so() -> None:
    assert _parameters("/api/graph/global") == {
        "node_types",
        "relations",
        "max_judgments",
    }
    assert _parameters("/api/graph/instruments") == {"relations"}
    assert _parameters("/api/graph/judgments") == {"max_judgments", "include_stubs"}

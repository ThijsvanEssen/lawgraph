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


def test_a_timeline_entry_is_typed_by_its_node_and_carries_no_free_body() -> None:
    schemas = SPEC["components"]["schemas"]
    entries = schemas["DossierTimelineResponse"]["properties"]["entries"]["items"]
    assert entries["discriminator"]["propertyName"] == "node_type"
    assert set(entries["discriminator"]["mapping"]) == {
        "document",
        "activity",
        "decision",
        "commitment",
    }
    for name in entries["discriminator"]["mapping"].values():
        body = schemas[name.rsplit("/", 1)[1]]["properties"]["body"]
        assert "$ref" in body, name  # a typed body, not an open object
    assert "committee" in schemas["TimelineActivityEntry"]["properties"]
    for body in ("TimelineDocumentBody", "TimelineDecisionBody"):
        assert "text" not in schemas[body]["properties"]
        assert "raw" not in schemas[body]["properties"]


def test_every_document_answer_says_its_chamber_source_and_kind() -> None:
    schemas = SPEC["components"]["schemas"]
    for name in (
        "DocumentSummaryDTO",
        "DocumentTextResponse",
        "DossierDocumentDTO",
        "TimelineDocumentBody",
    ):
        assert {"chamber", "source", "is_explanatory"} <= set(
            schemas[name]["properties"]
        ), name

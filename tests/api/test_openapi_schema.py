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


def test_an_explanation_says_what_it_points_at_and_how_far_it_reaches() -> None:
    schemas = SPEC["components"]["schemas"]
    operation = SPEC["paths"]["/api/articles/{bwb_id}/{article_number}/explained-by"]
    parameters = {p["name"]: p["schema"] for p in operation["get"]["parameters"]}
    assert (parameters["limit"]["minimum"], parameters["limit"]["maximum"]) == (1, 500)
    assert parameters["offset"]["minimum"] == 0

    explanation = schemas["ArticleExplanationDTO"]["properties"]
    assert {
        "document",
        "target",
        "target_id",
        "article_version_key",
        "confidence",
    } <= set(explanation)
    assert explanation["target"]["enum"] == ["article", "article_version", "instrument"]
    assert explanation["scope"]["enum"] == ["dossier", "article"]
    assert "section_anchor" in explanation
    document = schemas["ExplainingDocumentDTO"]["properties"]
    assert {"id", "key", "kind", "title", "date", "dossier_number", "chamber"} <= set(
        document
    )
    assert {"total", "items"} <= set(
        schemas["ArticleExplanationsResponse"]["properties"]
    )


def test_every_document_answer_says_its_chamber_source_and_kind() -> None:
    schemas = SPEC["components"]["schemas"]
    for name in (
        "DocumentSummaryDTO",
        "DocumentTextResponse",
        "DossierDocumentDTO",
        "TimelineDocumentBody",
        "ExplainingDocumentDTO",
    ):
        assert {"chamber", "source", "is_explanatory"} <= set(
            schemas[name]["properties"]
        ), name


def test_the_dossier_hub_and_the_authorship_lists_are_in_the_schema() -> None:
    schemas = SPEC["components"]["schemas"]
    detail = schemas["DossierDetailResponse"]["properties"]
    assert {"instruments", "committees", "documents_by_kind", "senate"} <= set(detail)
    assert schemas["DossierCommitteeDTO"]["properties"]["role"]["const"] == "lead"
    instrument = schemas["DossierInstrumentDTO"]["properties"]
    assert set(instrument["relation"]["enum"]) == {
        "legislated_in",
        "amends",
        "introduces",
        "repeals",
    }
    assert set(instrument["status"]["enum"]) == {"canoniek", "voorgesteld"}

    paths = SPEC["paths"]
    for path in (
        "/api/committees/{slug}/activities",
        "/api/members/{key}/dossiers",
        "/api/factions/{key}/dossiers",
    ):
        parameters = {p["name"]: p for p in paths[path]["get"]["parameters"]}
        assert parameters["limit"]["schema"]["maximum"] == 500, path
        assert parameters["offset"]["schema"]["minimum"] == 0, path

    committee = {
        p["name"]: p for p in paths["/api/committees/{slug}"]["get"]["parameters"]
    }
    assert {"status", "limit", "offset"} <= set(committee)
    assert "open" in str(committee["status"]["schema"])

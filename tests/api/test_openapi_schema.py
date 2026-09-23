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


def test_the_api_only_reads() -> None:
    """No route writes, so none asks for a key: a route that writes is a design change."""
    writing = [
        f"{method} {path}" for method, path, _ in OPERATIONS if method in WRITING
    ]
    assert writing == []
    assert "securitySchemes" not in SPEC.get("components", {})


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


def _properties(name: str) -> set[str]:
    return set(SPEC["components"]["schemas"][name]["properties"])


def test_an_article_says_where_its_parts_and_references_are() -> None:
    assert "parts" in _properties("ArticleSummaryDTO")
    assert "parts" in _properties("ArticleVersionDTO")
    assert {"id", "kind", "number", "text", "start", "end"} == _properties(
        "ArticlePartDTO"
    )
    assert "references" in _properties("ArticleDetailResponse")
    qualifier = {"leden", "onderdelen", "aanhef"}
    reference = {"kind", "bwb_id", "article", "doc", "text", "start", "end"}
    assert reference | qualifier == _properties("ArticleReferenceDTO")
    assert qualifier | {"reference_kind", "start", "end", "text"} <= _properties(
        "ArticleCitationSpan"
    )
    assert qualifier | {"reference_kind", "start", "end", "text"} <= _properties(
        "ArticleRelationshipWithType"
    )


def test_a_judgment_says_which_paragraphs_cite_which_article() -> None:
    qualifier = {"leden", "onderdelen", "aanhef"}
    assert "paragraph_id" in _properties("JudgmentParagraph")
    assert "cited_articles" in _properties("JudgmentDetailResponse")
    assert qualifier | {
        "article",
        "qualifier",
        "paragraph_ids",
        "paragraph_numbers",
        "snippet",
        "confidence",
        "mention_count",
    } == _properties("JudgmentCitedArticle")


def test_an_article_lists_the_passages_that_cite_it() -> None:
    operation = SPEC["paths"]["/api/articles/{bwb_id}/{article_number}/cited-by"]["get"]
    parameters = {p["name"]: p for p in operation["parameters"]}
    assert {"limit", "offset", "court", "tier", "lid"} <= set(parameters)
    assert (
        parameters["limit"]["schema"]["maximum"]
        >= parameters["limit"]["schema"]["default"]
    )
    assert parameters["offset"]["schema"]["minimum"] == 0
    assert {"article_id", "items", "total"} == _properties("ArticleCitedByResponse")
    assert {
        "judgment",
        "paragraph_id",
        "paragraph_number",
        "qualifier",
        "start",
        "end",
        "text",
        "snippet",
        "confidence",
        "leden",
        "onderdelen",
        "aanhef",
    } == _properties("ArticleCitedByItem")
    assert {
        "id",
        "key",
        "ecli",
        "court",
        "tier",
        "date",
        "display_name",
    } == _properties("CitedByJudgment")

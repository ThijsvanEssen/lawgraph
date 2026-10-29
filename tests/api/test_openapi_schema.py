"""What a client reads from ``/openapi.json``: every route described, typed and, when it
writes, marked with the key it asks for."""

from __future__ import annotations

import json
from typing import Any

import pytest

from lawgraph.api.app import app
from lawgraph.api.schemas.common import StrictModel
from lawgraph.config.settings import (
    API_REQUEST_TIMEOUT_MS,
    RATE_LIMIT_CALLS,
    RATE_LIMIT_PERIOD,
)

SPEC = app.openapi()
OPERATIONS = [
    (method.upper(), path, operation)
    for path, operations in SPEC["paths"].items()
    for method, operation in operations.items()
]
WRITING = {"POST", "PUT", "PATCH", "DELETE"}
# What a route may answer instead of JSON: a document of a standard format.
DOCUMENT_TYPES = {"application/atom+xml"}


def _answer_schema(operation: dict[str, Any]) -> dict[str, Any] | None:
    """The JSON schema of the 2xx answer; ``None`` for an answer without a body (204) or
    one that is a document of a standard format (the Atom feed)."""
    for status in ("200", "201"):
        content = operation["responses"].get(status, {}).get("content")
        if content and "application/json" not in content:
            assert set(content) <= DOCUMENT_TYPES, set(content)
            return None
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
    # Nor does a description promise what the writes made: badges, votes, watches.
    text = json.dumps(SPEC).lower()
    assert [
        word for word in ("expert badge", "community", "watch") if word in text
    ] == []


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
    assert explanation["target"]["enum"] == ["article", "article_version"]
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
        "establishes",
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
    views = {"props", "edge_meta"}
    assert _parameters(node) == filters | views | {"limit", "offset", "sort"}
    assert _parameters(f"{node}/neighborhood") == filters | views | {
        "depth",
        "cap",
        "stop_at",
    }
    assert "edge_meta" in _parameters("/api/paths")
    assert "passages" in _properties("NodeNeighborhoodEdge")

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
        "lid_counts",
        "capacity_counts",
        "tier_counts",
        "items",
    }


def _properties(name: str) -> set[str]:
    return set(SPEC["components"]["schemas"][name]["properties"])


def test_an_article_says_where_its_parts_and_references_are() -> None:
    assert "parts" in _properties("ArticleSummaryDTO")
    assert "parts" in _properties("ArticleVersionDTO")
    assert {"id", "kind", "number", "text", "start", "end", "term"} == _properties(
        "ArticlePartDTO"
    )
    assert "references" in _properties("ArticleDetailResponse")
    qualifier = {"leden", "onderdelen", "aanhef"}
    reference = {"kind", "bwb_id", "article", "celex", "doc", "text", "start", "end"}
    reference |= {"target", "footnote"}
    assert reference | qualifier == _properties("ArticleReferenceDTO")
    assert "footnote_references" in _properties("ArticleDetailResponse")
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
    place = {
        "paragraph_ids",
        "paragraph_numbers",
        "snippet",
        "snippet_paragraph_id",
        "footnote",
        "text",
        "start",
        "end",
        "confidence",
        "mention_count",
    }
    assert qualifier | place | {"article", "qualifier"} == _properties(
        "JudgmentCitedArticle"
    )
    assert place | {"id", "key", "path", "display_name", "ecli", "cite"} == _properties(
        "JudgmentCitedJudgment"
    )
    assert {"label", "paragraph_id", "at", "text", "citations"} == _properties(
        "JudgmentFootnote"
    )
    assert "footnotes" in _properties("JudgmentDTO")


def test_an_article_lists_the_passages_that_cite_it() -> None:
    operation = SPEC["paths"]["/api/articles/{bwb_id}/{article_number}/cited-by"]["get"]
    parameters = {p["name"]: p for p in operation["parameters"]}
    assert {"limit", "offset", "court", "tier", "year", "lid"} <= set(parameters)
    assert parameters["tier"]["schema"]["anyOf"][0]["type"] == "array"
    assert (
        parameters["limit"]["schema"]["maximum"]
        >= parameters["limit"]["schema"]["default"]
    )
    assert parameters["offset"]["schema"]["minimum"] == 0
    assert {
        "article_id",
        "items",
        "total",
        "judgment_total",
        "echr_judgment_total",
        "facets",
    } == _properties("ArticleCitedByResponse")
    assert {"year", "tier", "subject_area"} == _properties("CitedByFacets")
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
        "court_kind",
        "date",
        "display_name",
        "inbound_citation_count",
        "subject_areas",
        "outcome",
        "outcome_text",
        "conclusion_outcome",
        "conclusion_outcome_text",
        "echr_findings",
        "path",
        "cite",
    } == _properties("CitedByJudgment")


# The schema of an error (``api/errors.py``), which is no DTO of the API.
ERROR_SCHEMAS = {"HTTPValidationError"}


def test_every_object_schema_refuses_unknown_fields() -> None:
    """Every DTO is a ``StrictModel``: an object schema of the spec says
    ``additionalProperties: false`` (the shape of an error aside, which a 500 widens with
    its ``request_id``)."""
    loose = [
        name
        for name, schema in SPEC["components"]["schemas"].items()
        if name not in ERROR_SCHEMAS
        and schema.get("type") == "object"
        and "properties" in schema
        and schema.get("additionalProperties") is not False
    ]
    assert loose == []


def _subclasses[T](cls: type[T]) -> list[type[T]]:
    return [
        sub for direct in cls.__subclasses__() for sub in [direct, *_subclasses(direct)]
    ]


def test_every_field_an_answer_sends_is_required() -> None:
    """A DTO sends every field, also one with a default (``StrictModel``), so its schema
    requires it and a client needs no fallback for it; null is a value its type names.
    Only a field left out of the answer when null (``exclude_if``) is optional."""
    left_out = {
        f"{model.__name__}.{name}"
        for model in _subclasses(StrictModel)
        for name, field in model.model_fields.items()
        if field.exclude_if is not None
    }
    optional = {
        f"{name}.{field}"
        for name, schema in SPEC["components"]["schemas"].items()
        if name not in ERROR_SCHEMAS
        for field in schema.get("properties", {})
        if field not in schema.get("required", [])
    }
    assert "NodeNeighborhoodEdge.passages" in optional
    assert optional <= left_out


def test_every_limit_has_a_maximum() -> None:
    """A client reads the most it may ask from the schema (``api/params.py``), so it never
    asks past it and gets a 422."""
    unbounded = [
        f"{method} {path} {parameter['name']}"
        for method, path, operation in OPERATIONS
        for parameter in operation.get("parameters", [])
        if parameter["in"] == "query"
        and (parameter["name"] == "limit" or parameter["name"].endswith("_limit"))
        and "maximum" not in parameter["schema"]
    ]
    limits = [
        parameter["name"]
        for _, _, operation in OPERATIONS
        for parameter in operation.get("parameters", [])
        if parameter["name"] == "limit"
    ]
    assert len(limits) > 30 and unbounded == []


def test_the_schema_says_how_a_client_paces_itself() -> None:
    """How long the API reads for one request, and how many one client may make."""
    assert SPEC["info"]["x-request-timeout-ms"] == API_REQUEST_TIMEOUT_MS
    assert SPEC["info"]["x-rate-limit"] == {
        "calls": RATE_LIMIT_CALLS,
        "period_seconds": RATE_LIMIT_PERIOD,
    }

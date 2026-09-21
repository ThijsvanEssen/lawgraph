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

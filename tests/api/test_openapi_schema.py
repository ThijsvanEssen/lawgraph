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

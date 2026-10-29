"""Every route of the API, as (method, path) in the order the OpenAPI schema lists them: a
route that moves to another module keeps its address. And each route of a module under
``api/routes`` is served under ``/api/<the module's name>``.

Read from the schema and the routers themselves, not from ``app.routes``: since FastAPI 0.14x
an included router is one entry there, not its routes."""

from __future__ import annotations

import importlib
import pkgutil

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

import lawgraph.api.routes as routes
from lawgraph.api.app import app
from tests.asserts import assert_status

ROUTES = [
    ("GET", "/api/articles/batch"),
    ("GET", "/api/articles/{bwb_id}/{article_number}/text"),
    ("GET", "/api/articles/{bwb_id}/{article_number}"),
    ("GET", "/api/articles/{bwb_id}/{article_number}/cited-by"),
    ("GET", "/api/articles/{bwb_id}/{article_number}/history"),
    ("GET", "/api/articles/{bwb_id}/{article_number}/history/{version_key}"),
    ("GET", "/api/articles/{bwb_id}/{article_number}/legislative-history"),
    ("GET", "/api/articles/{bwb_id}/{article_number}/explained-by"),
    ("GET", "/api/articles/{bwb_id}/{article_number}/explanations"),
    ("GET", "/api/articles/{bwb_id}/{article_number}/delegated"),
    ("GET", "/api/judgments"),
    ("GET", "/api/judgments/{ecli}"),
    ("GET", "/api/instruments"),
    ("GET", "/api/instruments/{identifier}"),
    ("GET", "/api/instruments/{identifier}/definitions"),
    ("GET", "/api/instruments/{identifier}/eu-links"),
    ("GET", "/api/instruments/{bwb_id}/articles"),
    ("GET", "/api/instruments/{bwb_id}/judgments"),
    ("GET", "/api/instruments/{bwb_id}/dossiers"),
    ("GET", "/api/instruments/{bwb_id}/amended-by"),
    ("GET", "/api/instruments/{bwb_id}/related-instruments"),
    ("GET", "/api/instruments/{bwb_id}/references/{other}"),
    ("GET", "/api/instruments/{bwb_id}/delegated"),
    ("GET", "/api/instruments/{bwb_id}/basis"),
    ("GET", "/api/instruments/{bwb_id}/versions"),
    ("GET", "/api/instruments/{bwb_id}/articles/at/{at_date}"),
    ("GET", "/api/nodes/in-flux"),
    ("GET", "/api/nodes/in-flux/dossiers"),
    ("GET", "/api/nodes/heat"),
    ("GET", "/api/nodes/shared"),
    ("GET", "/api/nodes/{collection}/{key}"),
    ("GET", "/api/nodes/{collection}/{key}/neighborhood"),
    ("GET", "/api/nodes/{collection}/{key}/surroundings"),
    ("GET", "/api/dossiers"),
    ("GET", "/api/dossiers/{number}"),
    ("GET", "/api/dossiers/{number}/documents"),
    ("GET", "/api/dossiers/{number}/timeline"),
    ("GET", "/api/dossiers/{number}/amendments"),
    ("GET", "/api/dossiers/{number}/changed-articles"),
    ("GET", "/api/dossiers/{number}/mutations"),
    ("GET", "/api/committees"),
    ("GET", "/api/committees/{slug}"),
    ("GET", "/api/committees/{slug}/activities"),
    ("GET", "/api/members"),
    ("GET", "/api/members/{key}"),
    ("GET", "/api/members/{key}/votes"),
    ("GET", "/api/members/{key}/documents"),
    ("GET", "/api/members/{key}/dossiers"),
    ("GET", "/api/members/{key}/touched-instruments"),
    ("GET", "/api/factions"),
    ("GET", "/api/factions/{key}"),
    ("GET", "/api/factions/{key}/dossiers"),
    ("GET", "/api/factions/{key}/votes"),
    ("GET", "/api/factions/{key}/touched-instruments"),
    ("GET", "/api/ministries"),
    ("GET", "/api/ministries/{key}"),
    ("GET", "/api/cabinets"),
    ("GET", "/api/cabinets/{key}"),
    ("GET", "/api/cabinets/{key}/seats"),
    ("GET", "/api/commitments"),
    ("GET", "/api/commitments/{key}"),
    ("GET", "/api/activities/{key}"),
    ("GET", "/api/activities/{key}/records"),
    ("GET", "/api/parties/colors"),
    ("GET", "/api/relationships/types"),
    ("GET", "/api/relationships/search"),
    ("GET", "/api/annexes/{key}"),
    ("GET", "/api/documents"),
    ("GET", "/api/documents/{key}"),
    ("GET", "/api/documents/{key}/passages"),
    ("GET", "/api/resolve"),
    ("GET", "/api/search"),
    ("GET", "/api/stats"),
    ("GET", "/api/stats/coverage"),
    ("GET", "/api/decisions"),
    ("GET", "/api/decisions/{key}"),
    ("GET", "/api/decisions/{key}/document"),
    ("GET", "/api/parliament/seats"),
    ("GET", "/api/feed"),
    ("GET", "/api/feed/summary"),
    ("GET", "/api/feed/periods"),
    ("GET", "/api/paths"),
    ("GET", "/api/chains"),
    ("GET", "/api/lookup"),
    ("GET", "/api/feed.atom"),
    ("GET", "/"),
    ("GET", "/api/health"),
]


def test_every_route_keeps_its_method_and_path() -> None:
    assert [
        (method.upper(), path)
        for path, operations in app.openapi()["paths"].items()
        for method in operations
    ] == ROUTES


def test_each_route_lives_in_the_module_of_its_prefix() -> None:
    """``routes/<name>.py`` serves ``/api/<name>``; ``render`` (no schema) serves
    ``/render``."""
    served = set(app.openapi()["paths"])
    missing = [
        f"/api/{info.name}{route.path}"
        for info in pkgutil.iter_modules(routes.__path__)
        if info.name != "render"
        for route in importlib.import_module(
            f"{routes.__name__}.{info.name}"
        ).router.routes
        if isinstance(route, APIRoute) and f"/api/{info.name}{route.path}" not in served
    ]
    assert missing == []
    render = importlib.import_module(f"{routes.__name__}.render").router.routes
    assert [
        (method, route.path)
        for route in render
        if isinstance(route, APIRoute)
        for method in sorted(route.methods or ())
    ] == [("GET", "/render/{path:path}"), ("HEAD", "/render/{path:path}")]


def test_the_schema_and_its_page_are_served_under_the_api_prefix() -> None:
    """The proxy sends only ``/api/*`` to the API: the schema and its interactive page
    live there, not at the root FastAPI puts them by default."""
    client = TestClient(app)
    schema = client.get("/api/openapi.json")
    page = client.get("/api/docs")
    assert_status(schema, 200)
    assert schema.json()["paths"].keys() == app.openapi()["paths"].keys()
    assert_status(page, 200)
    assert "/api/openapi.json" in page.text
    assert_status(client.get("/openapi.json"), 404)

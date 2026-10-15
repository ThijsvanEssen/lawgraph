"""Every route of the API, as (method, path) in the order the app lists them: a route that
moves to another module keeps its address. And each route under ``/api/<name>`` lives in the
route module of that name."""

from __future__ import annotations

import re

from fastapi.routing import APIRoute

from lawgraph.api.app import app

ROUTES = [
    ("GET", "/api/articles/{bwb_id}/{article_number}"),
    ("GET", "/api/articles/{bwb_id}/{article_number}/cited-by"),
    ("GET", "/api/articles/{bwb_id}/{article_number}/history"),
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
    ("GET", "/api/nodes/heat"),
    ("GET", "/api/nodes/{collection}/{key}"),
    ("GET", "/api/nodes/{collection}/{key}/neighborhood"),
    ("GET", "/api/dossiers"),
    ("GET", "/api/dossiers/{number}"),
    ("GET", "/api/dossiers/{number}/documents"),
    ("GET", "/api/dossiers/{number}/timeline"),
    ("GET", "/api/dossiers/{number}/changed-articles"),
    ("GET", "/api/dossiers/{number}/mutations"),
    ("GET", "/api/committees"),
    ("GET", "/api/committees/{slug}"),
    ("GET", "/api/committees/{slug}/activities"),
    ("GET", "/api/members"),
    ("GET", "/api/members/{key}"),
    ("GET", "/api/members/{key}/votes"),
    ("GET", "/api/members/{key}/dossiers"),
    ("GET", "/api/members/{key}/touched-instruments"),
    ("GET", "/api/factions"),
    ("GET", "/api/factions/{key}"),
    ("GET", "/api/factions/{key}/dossiers"),
    ("GET", "/api/factions/{key}/votes"),
    ("GET", "/api/factions/{key}/touched-instruments"),
    ("GET", "/api/ministries"),
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
    ("GET", "/api/lookup"),
    ("GET", "/api/feed.atom"),
    ("GET", "/render/{path:path}"),
    ("HEAD", "/render/{path:path}"),
    ("GET", "/"),
    ("GET", "/api/health"),
]


def test_every_route_keeps_its_method_and_path() -> None:
    assert [
        (method, route.path)
        for route in app.routes
        if isinstance(route, APIRoute)
        for method in sorted(route.methods)
    ] == ROUTES


def test_each_route_lives_in_the_module_of_its_prefix() -> None:
    misplaced = [
        (route.path, route.endpoint.__module__)
        for route in app.routes
        if isinstance(route, APIRoute)
        and (prefix := re.match(r"/api/([a-z]+)", route.path))
        and route.endpoint.__module__ != "lawgraph.api.app"
        and route.endpoint.__module__ != f"lawgraph.api.routes.{prefix[1]}"
    ]
    assert misplaced == []

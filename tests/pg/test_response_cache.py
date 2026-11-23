"""Whole answers of the API kept per data version on a real PostgreSQL
(``api/response_cache``): a page asked again is given at once, equal requests at the same
moment are computed once, a write gives the new page, and a page past its budget is
computed whole in the background for the next request."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Iterator
from pathlib import Path
from typing import Any

import httpx
import pytest

from lawgraph.api import response_cache
from lawgraph.api.app import app
from lawgraph.api.dependencies import get_store
from lawgraph.api.routes import render
from lawgraph.api.seo import shell
from lawgraph.config import settings
from lawgraph.db import GraphStore, whole_answers
from tests.asserts import assert_status
from tests.fakes import PATIENCE

PAGE = "/render/wetten/BWBR0005289/artikel/6:162"
SHELL = (
    "<!doctype html><html><head><title>Concordans</title></head><body></body></html>"
)


def _article(heading: str) -> dict[str, Any]:
    return {
        "key": "bwbr0005289_162",
        "type": "article",
        "labels": ["BWB"],
        "props": {
            "bwb_id": "BWBR0005289",
            "article_number": "162",
            "heading": heading,
            "position": 162,
            "instrument_citation_title": "Burgerlijk Wetboek Boek 6",
            "text": "1. Hij die jegens een ander een onrechtmatige daad pleegt …",
        },
    }


@pytest.fixture()
def served(
    store: GraphStore, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Iterator[GraphStore]:
    index = tmp_path / "index.html"
    index.write_text(SHELL)
    (tmp_path / "spa-routes.json").write_text(json.dumps([]))
    monkeypatch.setattr(settings, "SPA_INDEX", str(index))
    monkeypatch.setattr(whole_answers, "RESPONSE_BYTES", 16 * 2**20)
    # a write is followed by its new page, however slow the runner
    monkeypatch.setattr(response_cache, "STALE_WAIT", PATIENCE)
    shell.forget()
    store.bulk_insert_or_update_nodes(
        "instruments",
        [
            {
                "key": "bwbr0005289",
                "type": "instrument",
                "labels": ["BWB"],
                "props": {
                    "bwb_id": "BWBR0005289",
                    "citation_title": "Burgerlijk Wetboek Boek 6",
                    "kind": "wet",
                },
            }
        ],
    )
    store.bulk_insert_or_update_nodes("articles", [_article("Onrechtmatige daad")])
    app.dependency_overrides[get_store] = lambda: store
    try:
        yield store
    finally:
        app.dependency_overrides.pop(get_store, None)
        shell.forget()


def _run(test: Callable[[httpx.AsyncClient], Awaitable[None]]) -> None:
    async def main() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://t"
        ) as client:
            await test(client)

    asyncio.run(main())


def _timing(response: httpx.Response) -> dict[str, str]:
    """The ``Server-Timing`` of *response*: ``total`` and ``cache`` (its ``desc``)."""
    found: dict[str, str] = {}
    for metric in response.headers.get("server-timing", "").split(","):
        name, *parts = metric.strip().split(";")
        for part in parts:
            key, _, value = part.partition("=")
            if (name, key) in (("total", "dur"), ("cache", "desc")):
                found[name] = value
    return found


def _counted(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The pages rendered from now on (one ``_source_page`` each)."""
    rendered: list[str] = []
    source_page = render._source_page

    def counted(store: GraphStore, pad: Any, node_id: str) -> Any:
        rendered.append(node_id)
        return source_page(store, pad, node_id)

    monkeypatch.setattr(render, "_source_page", counted)
    return rendered


def test_a_page_asked_again_is_given_at_once(
    served: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    rendered = _counted(monkeypatch)

    async def test(client: httpx.AsyncClient) -> None:
        first = await client.get(PAGE)
        assert_status(first, 200)
        again = await client.get(PAGE)
        assert_status(again, 200)
        assert again.text == first.text
        assert _timing(again)["cache"] == "hit"
        assert float(_timing(again)["total"]) < 10
        node = "/api/nodes/articles/bwbr0005289_162"
        await client.get(node)
        assert _timing(await client.get(node))["cache"] == "hit"

    _run(test)
    assert rendered == ["articles/bwbr0005289_162"]


def test_twenty_equal_requests_at_once_render_the_page_once(
    served: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    rendered = _counted(monkeypatch)

    async def test(client: httpx.AsyncClient) -> None:
        answers = await asyncio.gather(*(client.get(PAGE) for _ in range(20)))
        for answer in answers:
            assert_status(answer, 200)
        assert len({answer.text for answer in answers}) == 1

    _run(test)
    assert rendered == ["articles/bwbr0005289_162"]


def test_a_write_gives_the_new_page(served: GraphStore) -> None:
    async def test(client: httpx.AsyncClient) -> None:
        assert "Onrechtmatige daad" in (await client.get(PAGE)).text
        served.bulk_insert_or_update_nodes("articles", [_article("Schadevergoeding")])
        again = await client.get(PAGE)
        assert "Schadevergoeding" in again.text

    _run(test)


def test_a_page_past_its_budget_is_rendered_whole_for_the_next_request(
    served: GraphStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(render, "RENDER_BUDGET", 0.0)

    async def test(client: httpx.AsyncClient) -> None:
        late = await client.get(PAGE)
        assert_status(late, 503)
        assert late.headers[render.LATE_HEADER] == "1"
        for _ in range(int(PATIENCE / 0.01)):
            if whole_answers._kept:
                break
            await asyncio.sleep(0.01)
        whole = await client.get(PAGE)
        assert_status(whole, 200)
        assert "Hij die jegens een ander" in whole.text
        assert _timing(whole)["cache"] == "hit"

    _run(test)

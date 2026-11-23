"""Whole answers kept per data version (``api/response_cache``): computed once for equal
requests at the same moment, the old one given until the new one is done but never 6 hours
after a newer version came, a short one computed whole in the background, bounded by bytes.

An app of its own stands in for the routes: it counts what it computes and can be held."""

from __future__ import annotations

import asyncio
import gzip
import json
from collections.abc import Awaitable, Callable, Iterator
from typing import Any

import httpx
import pytest
from starlette.types import Receive, Scope, Send

from lawgraph.api import response_cache
from lawgraph.api.middleware import ReadDeadlineMiddleware
from lawgraph.api.response_cache import ResponseCacheMiddleware
from lawgraph.db import version_cache, whole_answers
from lawgraph.db.request_context import ReadTimedOut, read_budget, read_time_left
from tests.asserts import assert_status
from tests.fakes import PATIENCE, ManualClock


class _Data:
    """A database whose data version changes when told."""

    name = "response-test"

    def __init__(self) -> None:
        self.version = "1"

    def data_version(self) -> str:
        return self.version


class _Routes:
    """The app behind the cache: an answer of the path, the query and the data version;
    *held* keeps it from answering until set; a path with ``short`` runs out of its budget
    unless computed patiently."""

    def __init__(self, data: _Data) -> None:
        self.data = data
        self.computed: list[str] = []
        self.held: asyncio.Event | None = None
        self.status = 200
        self.headers: list[tuple[bytes, bytes]] = []

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        self.computed.append(scope["path"])
        if self.held is not None:
            await self.held.wait()
        status, short = self.status, False
        if "short" in scope["path"]:
            with read_budget(0.05, "a part") as budget:
                if (read_time_left() or 0) < 1:
                    raise ReadTimedOut("late")
            short = budget.ran_out
            status = 503 if short else 200
        body = json.dumps(
            {
                "path": scope["path"],
                "query": scope["query_string"].decode(),
                "version": self.data.version,
                "short": short,
                "padding": "x" * 2000,
            }
        ).encode()
        headers = [
            (b"content-type", b"application/json"),
            (b"etag", f'W/"{self.data.version}"'.encode()),
            *self.headers,
        ]
        if short:
            headers.append((b"cache-control", b"no-store"))
        await send(
            {"type": "http.response.start", "status": status, "headers": headers}
        )
        await send({"type": "http.response.body", "body": body})


@pytest.fixture(autouse=True)
def _kept(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.setattr(whole_answers, "RESPONSE_BYTES", 16 * 2**20)
    yield


@pytest.fixture
def data() -> _Data:
    return _Data()


@pytest.fixture
def routes(data: _Data) -> _Routes:
    return _Routes(data)


def _run(
    routes: _Routes, data: object, test: Callable[[httpx.AsyncClient], Awaitable[None]]
) -> None:
    """Run *test* with a client of the cache over *routes* (as in the app: the deadline of
    a request within the cache, gzip within it too)."""
    from starlette.middleware.gzip import GZipMiddleware

    inner = GZipMiddleware(ReadDeadlineMiddleware(routes), minimum_size=1000)
    app = ResponseCacheMiddleware(inner, store=lambda: data, api_version="9")  # type: ignore[arg-type,return-value]

    async def main() -> None:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://t"
        ) as client:
            await test(client)

    asyncio.run(main())


def _cache(response: httpx.Response) -> str:
    timing = response.headers.get("server-timing", "")
    return (
        timing.split("cache;desc=")[1].split(";")[0] if "cache;desc=" in timing else ""
    )


async def _kept_now(path: str) -> bool:
    """Whether an answer of *path* is kept within ``PATIENCE`` (a computation in the
    background ends)."""
    for _ in range(int(PATIENCE / 0.01)):
        if any(path in str(key) for key in whole_answers._kept):
            return True
        await asyncio.sleep(0.01)
    return False


def test_a_second_request_is_given_the_kept_answer(
    routes: _Routes, data: _Data
) -> None:
    async def test(client: httpx.AsyncClient) -> None:
        first = await client.get("/render/wetten/a")
        second = await client.get("/render/wetten/a")
        assert first.json() == second.json()
        assert _cache(second) == "hit"
        assert second.headers["content-encoding"] == "gzip"
        assert second.headers["x-request-id"] != first.headers.get("x-request-id")
        plain = await client.get(
            "/render/wetten/a", headers={"accept-encoding": "identity"}
        )
        assert "content-encoding" not in plain.headers
        assert plain.json() == first.json()

    _run(routes, data, test)
    assert routes.computed == ["/render/wetten/a"]


def test_twenty_equal_requests_at_once_are_computed_once(
    routes: _Routes, data: _Data
) -> None:
    async def test(client: httpx.AsyncClient) -> None:
        routes.held = asyncio.Event()
        asking = [
            asyncio.create_task(client.get("/api/nodes/articles/a")) for _ in range(20)
        ]
        while not routes.computed:
            await asyncio.sleep(0.01)
        await asyncio.sleep(0.05)
        routes.held.set()
        answers = await asyncio.gather(*asking)
        for answer in answers:
            assert_status(answer, 200)
        assert len({a.text for a in answers}) == 1
        assert sorted(_cache(a) for a in answers).count("shared") == 19

    _run(routes, data, test)
    assert routes.computed == ["/api/nodes/articles/a"]


def test_the_old_answer_is_given_until_the_new_one_is_done(
    routes: _Routes, data: _Data
) -> None:
    async def test(client: httpx.AsyncClient) -> None:
        await client.get("/api/stats")
        data.version = "2"
        routes.held = asyncio.Event()
        old = await client.get("/api/stats")
        assert old.json()["version"] == "1"
        assert _cache(old) == "stale"
        assert old.headers["etag"] == 'W/"1"'  # the tag of the body it has
        again = await client.get("/api/stats")  # one computation of the new one
        assert _cache(again) == "stale"
        routes.held.set()
        for _ in range(int(PATIENCE / 0.01)):
            new = await client.get("/api/stats")
            if new.json()["version"] == "2":
                break
            await asyncio.sleep(0.01)
        assert new.json()["version"] == "2"

    _run(routes, data, test)
    assert routes.computed == ["/api/stats", "/api/stats"]


@pytest.mark.parametrize(("hours", "old"), [(5.99, True), (6.01, False)])
def test_the_old_answer_is_never_given_six_hours_after_a_newer_version(
    monkeypatch: pytest.MonkeyPatch,
    routes: _Routes,
    data: _Data,
    hours: float,
    old: bool,
) -> None:
    clock = ManualClock()
    monkeypatch.setattr(version_cache, "_clock", clock)
    monkeypatch.setattr(response_cache, "STALE_WAIT", 0.0)

    async def test(client: httpx.AsyncClient) -> None:
        await client.get("/render/wetten/a")
        clock.advance(3600)  # the answer was computed an hour before the data changed
        data.version = "2"
        await client.get("/render/uitspraken/b")  # the new version is seen
        clock.advance(hours * 3600)
        routes.held = asyncio.Event()
        asking = asyncio.create_task(client.get("/render/wetten/a"))
        await asyncio.sleep(0.1)
        routes.held.set()
        answer = await asking
        assert answer.json()["version"] == ("1" if old else "2")

    _run(routes, data, test)


def test_while_the_pipelines_write_the_old_answer_is_given_as_it_is(
    monkeypatch: pytest.MonkeyPatch, routes: _Routes, data: _Data
) -> None:
    clock = ManualClock()
    monkeypatch.setattr(version_cache, "_clock", clock)

    async def test(client: httpx.AsyncClient) -> None:
        await client.get("/render/wetten/a")
        for version in ("2", "3"):  # versions over a minute apart: a run
            data.version = version
            await client.get("/render/uitspraken/b")  # the version is seen
            clock.advance(version_cache.RUN_AFTER + 1)
        answer = await client.get("/render/wetten/a")
        assert (answer.json()["version"], _cache(answer)) == ("1", "stale")

    _run(routes, data, test)
    assert routes.computed.count("/render/wetten/a") == 1


def test_a_short_answer_is_computed_whole_in_the_background(
    routes: _Routes, data: _Data
) -> None:
    async def test(client: httpx.AsyncClient) -> None:
        late = await client.get("/render/wetten/short")
        assert_status(late, 503)
        assert late.json()["short"] is True
        assert await _kept_now("/render/wetten/short")
        whole = await client.get("/render/wetten/short")
        assert_status(whole, 200)
        assert (whole.json()["short"], _cache(whole)) == (False, "hit")

    _run(routes, data, test)
    assert routes.computed == ["/render/wetten/short"] * 2


def test_a_request_while_the_whole_answer_computes_gets_the_short_one(
    routes: _Routes, data: _Data, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(response_cache, "FILL_WAIT", 0.05)

    async def test(client: httpx.AsyncClient) -> None:
        await client.get("/render/wetten/short")
        routes.held = asyncio.Event()  # holds the computation in the background
        while len(routes.computed) < 2:
            await asyncio.sleep(0.01)
        meanwhile = await client.get("/render/wetten/short")
        assert_status(meanwhile, 503)
        assert _cache(meanwhile) == "late"
        routes.held.set()
        assert await _kept_now("/render/wetten/short")

    _run(routes, data, test)
    assert len(routes.computed) == 2


@pytest.mark.parametrize(
    ("path", "headers", "status", "answer_headers"),
    [
        ("/api/search?q=huur", {}, 200, []),
        ("/api/health", {}, 200, []),
        ("/api/stats", {"authorization": "Bearer x"}, 200, []),
        ("/api/stats?q=" + "x" * 1100, {}, 200, []),
        ("/api/stats", {}, 500, []),
        ("/api/stats", {}, 503, []),
        ("/api/stats", {}, 200, [(b"cache-control", b"no-store")]),
        ("/api/stats", {}, 200, [(b"set-cookie", b"a=b")]),
        ("/", {}, 200, []),
    ],
)
def test_what_is_not_kept_is_computed_every_time(
    routes: _Routes,
    data: _Data,
    path: str,
    headers: dict[str, str],
    status: int,
    answer_headers: list[tuple[bytes, bytes]],
) -> None:
    routes.status, routes.headers = status, answer_headers

    async def test(client: httpx.AsyncClient) -> None:
        for _ in range(2):
            await client.get(path, headers=headers)

    _run(routes, data, test)
    assert len(routes.computed) == 2


@pytest.mark.parametrize("status", [301, 404, 410])
def test_a_redirect_and_a_page_not_found_or_gone_are_kept(
    routes: _Routes, data: _Data, status: int
) -> None:
    routes.status = status

    async def test(client: httpx.AsyncClient) -> None:
        for _ in range(2):
            await client.get("/render/bestaatniet")

    _run(routes, data, test)
    assert len(routes.computed) == 1


def test_the_parameters_of_a_query_in_another_order_are_one_answer(
    routes: _Routes, data: _Data
) -> None:
    async def test(client: httpx.AsyncClient) -> None:
        await client.get("/api/judgments?court=hr&page=2")
        answer = await client.get("/api/judgments?page=2&court=hr")
        assert _cache(answer) == "hit"
        other = await client.get("/api/judgments?page=3&court=hr")
        assert other.json()["query"] == "page=3&court=hr"

    _run(routes, data, test)
    assert len(routes.computed) == 2


def test_a_client_with_the_tag_gets_304_and_a_head_no_body(
    routes: _Routes, data: _Data
) -> None:
    async def test(client: httpx.AsyncClient) -> None:
        first = await client.get("/render/wetten/a")
        same = await client.get(
            "/render/wetten/a", headers={"if-none-match": first.headers["etag"]}
        )
        assert_status(same, 304)
        assert same.content == b""
        assert same.headers["etag"] == first.headers["etag"]
        head = await client.head("/render/wetten/a")
        assert_status(head, 200)
        assert (head.content, _cache(head)) == (b"", "hit")

    _run(routes, data, test)
    assert len(routes.computed) == 1


def test_the_first_request_with_the_tag_gets_304_too(
    routes: _Routes, data: _Data
) -> None:
    async def test(client: httpx.AsyncClient) -> None:
        answer = await client.get(
            "/render/wetten/a", headers={"if-none-match": 'W/"1"'}
        )
        assert_status(answer, 304)

    _run(routes, data, test)


def test_the_kept_answers_hold_no_more_bytes_than_allowed(
    monkeypatch: pytest.MonkeyPatch, routes: _Routes, data: _Data
) -> None:
    monkeypatch.setattr(whole_answers, "RESPONSE_BYTES", 64 * 1000)

    async def test(client: httpx.AsyncClient) -> None:
        for n in range(200):
            await client.get(f"/render/wetten/{n}")
        assert 0 < whole_answers._bytes <= whole_answers.RESPONSE_BYTES
        assert _cache(await client.get("/render/wetten/199")) == "hit"
        await client.get("/render/wetten/0")  # the one used longest ago went first

    _run(routes, data, test)
    assert routes.computed.count("/render/wetten/0") == 2


def test_a_store_without_a_data_version_keeps_nothing(routes: _Routes) -> None:
    class _Fake:
        name = "fake"

    async def test(client: httpx.AsyncClient) -> None:
        for _ in range(2):
            await client.get("/render/wetten/a")

    _run(routes, _Fake(), test)
    assert len(routes.computed) == 2


def test_the_answer_of_a_kept_page_unpacks_to_its_json(
    routes: _Routes, data: _Data
) -> None:
    kept: dict[str, Any] = {}

    async def test(client: httpx.AsyncClient) -> None:
        await client.get("/api/stats")
        entry = next(iter(whole_answers._kept.values()))
        kept.update(json.loads(gzip.decompress(entry.value.body)))

    _run(routes, data, test)
    assert kept["path"] == "/api/stats"

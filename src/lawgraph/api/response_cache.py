"""Whole answers of ``/render`` and ``/api`` (GET and HEAD), kept as the bytes a client gets
(gzip) per path, query (its parameters in order of name), API version, shell of the front end
(a page names its chunks) and day, for the data version they were computed for
(``whole_answers``):

- a request that finds the answer of the data version now gets it at once
  (``cache;desc=hit``), 304 when its ``If-None-Match`` names its ``ETag``;
- one that finds the answer of a version before, left at most ``MAX_STALE`` (6 h) ago,
  gets it while the new one computes in the background, after waiting ``STALE_WAIT`` for
  that at most (``cache;desc=stale``); while the pipelines write nothing is computed;
- equal requests at the same moment wait for the one computation of the first, which runs
  in its own deadline and goes on when its client leaves (``cache;desc=shared``);
- an answer that lacks a part because a budget ran out (a page late, 503 with
  ``X-Render-Late``, or one without its first paint) is not kept: it is computed again in
  the background without those budgets (``patient``), on the background connections,
  ``FILLS`` at a time, and kept for the next request. One that asks meanwhile waits
  ``FILL_WAIT`` for it, then gets the answer that was short (``cache;desc=late``).

Kept: 200, 301, 404 and 410 without ``no-store`` (a partial answer, ``no_store_if``) and
without a cookie. Never kept: a search (its words are counted, and are a long tail), the
health of the API, a query longer than ``MAX_QUERY``, a request with ``Authorization`` or
``Range``. No route answers per visitor (no cookies, no authentication). A client's own
``Cache-Control`` is not followed: a crawler that sends ``no-cache`` gets the kept answer.
"""

from __future__ import annotations

import asyncio
import contextvars
import dataclasses
import gzip
import time
import uuid
from collections.abc import Callable, Hashable
from typing import cast
from urllib.parse import parse_qsl, urlencode

from starlette.types import ASGIApp, Message, Receive, Scope, Send

from lawgraph.api.middleware import (
    ASKED,
    FILL,
    VersionReader,
    if_none_match,
    log_answer,
    request_line,
)
from lawgraph.api.seo import shell
from lawgraph.config.settings import API_REQUEST_TIMEOUT_MS
from lawgraph.core.logging import describe, get_logger
from lawgraph.core.time import dutch_today
from lawgraph.db import GraphStore, version_cache, whole_answers
from lawgraph.db.request_context import in_background, patient, watching_budgets

logger = get_logger(__name__)

KEPT_STATUSES = frozenset({200, 301, 404, 410})
UNCACHED = ("/api/search", "/api/health", "/api/docs")
MAX_QUERY = 1024
# How long a request that has the answer of a version before waits for the new one (seconds).
STALE_WAIT = version_cache.STALE_WAIT
# How long a request without one waits for an answer computed in the background (seconds):
# Caddy serves the static shell after 2 s.
FILL_WAIT = 1.0
# How long a request waits for the computation of an equal one (seconds): its own deadline.
REQUEST_WAIT = API_REQUEST_TIMEOUT_MS / 1000
# What a kept answer costs beside its body, its headers and its key (bytes): the objects
# around them and its place in the order.
OVERHEAD = 512
# Headers of the request that computed an answer, not of the answer.
_OWN = (b"x-request-id", b"server-timing")
_NOT_MODIFIED = (b"etag", b"cache-control", b"vary", *_OWN)


@dataclasses.dataclass(frozen=True)
class Answer:
    """A whole answer: status, headers and body; *short* when a budget ran out."""

    status: int
    headers: list[tuple[bytes, bytes]]
    body: bytes
    short: bool = False

    def header(self, name: bytes) -> bytes | None:
        return next((v for n, v in self.headers if n.lower() == name), None)

    @property
    def keepable(self) -> bool:
        return (
            self.status in KEPT_STATUSES
            and not self.short
            and b"no-store" not in (self.header(b"cache-control") or b"")
            and self.header(b"set-cookie") is None
        )

    def shared(self) -> Answer:
        """The answer without the headers of the request that computed it."""
        headers = [(n, v) for n, v in self.headers if n.lower() not in _OWN]
        return dataclasses.replace(self, headers=headers)


def cacheable(scope: Scope) -> bool:
    """Whether the answer to *scope* may be kept (see the module)."""
    path = str(scope.get("path", ""))
    return (
        scope["type"] == "http"
        and scope.get("method") in ("GET", "HEAD")
        and path.startswith(("/render/", "/api/"))
        and not path.startswith(UNCACHED)
        and len(scope.get("query_string", b"")) <= MAX_QUERY
        and not any(n in (b"authorization", b"range") for n, _ in scope["headers"])
    )


class ResponseCacheMiddleware:
    """Keeps whole answers (see the module); a store without a data version (a fake), or
    ``RESPONSE_BYTES`` 0, keeps nothing."""

    def __init__(
        self, app: ASGIApp, store: Callable[[], GraphStore], api_version: str
    ) -> None:
        self._app = app
        self._versions = VersionReader(store)
        self._api_version = api_version
        self._tasks: set[asyncio.Task[None]] = set()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        version = None
        if whole_answers.RESPONSE_BYTES > 0 and cacheable(scope):
            version = await self._versions.current()
        database = self._versions.database
        if version is None or database is None:
            await self._app(scope, receive, send)
            return
        started = time.perf_counter()
        key = self._key(scope)
        found = whole_answers.look(database, version, key)
        answer, how = await self._answer(scope, database, version, key, found)
        if answer is None:
            # waited in vain for an equal request: computed as without the cache
            await self._app(scope, receive, send)
            return
        await _send(scope, send, answer, how, started)

    def _key(self, scope: Scope) -> Hashable:
        path = str(scope["path"])
        pairs = parse_qsl(
            scope["query_string"].decode("latin-1"), keep_blank_values=True
        )
        query = urlencode(sorted(pairs, key=lambda pair: pair[0]))
        page = shell.stamp() if path.startswith("/render/") else ""
        return ("response", path, query, self._api_version, page, str(dutch_today()))

    async def _answer(
        self,
        scope: Scope,
        database: str,
        version: str,
        key: Hashable,
        found: whole_answers.Look,
    ) -> tuple[Answer | None, str]:
        if found.kept is not None and found.fresh:
            return cast(Answer, found.kept.value), "hit"
        if found.kept is not None:
            computing = found.computing
            if computing is None and found.refresh:
                computing = self._fill(scope, database, version, key)
            new = None if computing is None else await _wait(computing, STALE_WAIT)
            if new is not None and new.keepable:
                return new, "shared"
            return cast(Answer, found.kept.value), "stale"
        computing = found.computing
        assert computing is not None
        if found.lead:
            return await self._lead(scope, database, version, key, computing), "own"
        answer = await _wait(
            computing, FILL_WAIT if computing.background else REQUEST_WAIT
        )
        if answer is None and computing.interim is not None:
            return cast(Answer, computing.interim), "late"
        return answer, "shared"

    async def _lead(
        self,
        scope: Scope,
        database: str,
        version: str,
        key: Hashable,
        computing: whole_answers.Computing,
    ) -> Answer:
        """The answer computed for this request, kept, and given to the equal requests
        that waited for it; a short one is computed again in the background."""
        try:
            answer = await self._compute(scope)
        except BaseException as exc:
            whole_answers.settle(database, key, computing, exc)
            raise
        shared = answer.shared()
        whole_answers.settle(
            database, key, computing, shared, _kept(key, version, shared)
        )
        if answer.short:
            self._fill(scope, database, version, key, interim=shared)
        return answer

    def _fill(
        self,
        scope: Scope,
        database: str,
        version: str,
        key: Hashable,
        interim: Answer | None = None,
    ) -> whole_answers.Computing | None:
        """Compute the answer to *scope* in the background (``whole_answers.fill``): in a
        context of its own, without the deadline or the client of the request."""
        computing = whole_answers.fill(database, key, interim)
        if computing is None:
            return None
        task = asyncio.get_running_loop().create_task(
            self._filled(scope, database, version, key, computing),
            context=contextvars.Context(),
        )
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)
        return computing

    async def _filled(
        self,
        scope: Scope,
        database: str,
        version: str,
        key: Hashable,
        computing: whole_answers.Computing,
    ) -> None:
        try:
            with in_background(), patient():
                answer = (await self._compute(scope, fill=True)).shared()
        except BaseException as exc:
            whole_answers.settle(database, key, computing, exc)
            if not isinstance(exc, Exception):
                raise
            logger.warning(
                "Computing %s in the background failed: %s",
                scope.get("path"),
                describe(exc),
            )
            return
        whole_answers.settle(
            database, key, computing, answer, _kept(key, version, answer)
        )

    async def _compute(self, scope: Scope, fill: bool = False) -> Answer:
        """The whole answer of the app to *scope*, gzip, never 304, for a client that never
        leaves; *fill*: marked so in the log."""
        status = 500
        headers: list[tuple[bytes, bytes]] = []
        body: list[bytes] = []

        async def capture(message: Message) -> None:
            nonlocal status, headers
            if message["type"] == "http.response.start":
                status, headers = message["status"], list(message.get("headers", []))
            elif message["type"] == "http.response.body":
                body.append(message.get("body", b""))

        with watching_budgets() as budget:
            await self._app(_inner(scope, fill), _staying(), capture)
        return Answer(status, headers, b"".join(body), budget.ran_out)


def _kept(key: Hashable, version: str, answer: Answer) -> whole_answers.Kept | None:
    """*answer* as kept for *key* of *version*, with what it costs in memory; None when
    it is not to be kept."""
    if not answer.keepable:
        return None
    size = (
        len(answer.body)
        + sum(len(n) + len(v) for n, v in answer.headers)
        + sum(len(str(part)) for part in cast(tuple[object, ...], key))
        + OVERHEAD
    )
    return whole_answers.Kept(version, answer, size)


def _inner(scope: Scope, fill: bool) -> Scope:
    """The request as the app gets it: a GET, gzip, without ``If-None-Match`` (the cache
    answers that); *fill* without a client, marked ``FILL``."""
    headers = [
        (n, v)
        for n, v in scope["headers"]
        if n not in (b"if-none-match", b"accept-encoding")
    ]
    inner = {
        **scope,
        "method": "GET",
        ASKED: scope["method"],
        "headers": [*headers, (b"accept-encoding", b"gzip")],
        "state": dict(scope.get("state") or {}),
    }
    if fill:
        inner[FILL] = True
        inner["client"] = None
    return inner


def _staying() -> Receive:
    """The messages of a client that sent its request and never leaves: what is computed
    is kept for the next request whatever the one that asked does."""
    sent = False

    async def receive() -> Message:
        nonlocal sent
        if not sent:
            sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await asyncio.Event().wait()
        return {"type": "http.disconnect"}

    return receive


async def _wait(computing: whole_answers.Computing, limit: float) -> Answer | None:
    """The answer *computing* gets within *limit* seconds; None past it or on a failure."""
    waiting = asyncio.wrap_future(computing.future)
    # a failure that comes after the wait is read, not logged as never read
    waiting.add_done_callback(lambda f: f.cancelled() or f.exception())
    done, _ = await asyncio.wait({waiting}, timeout=limit)
    if not done or waiting.cancelled() or waiting.exception() is not None:
        return None
    return cast(Answer, waiting.result())


async def _send(
    scope: Scope, send: Send, answer: Answer, how: str, started: float
) -> None:
    """Send *answer*: 304 when the client has it, unpacked for a client without gzip, no
    body to a HEAD; one not computed for this request (*how* not ``own``) with an id, a
    ``Server-Timing`` and a line in the log of its own."""
    status, headers, body = answer.status, list(answer.headers), answer.body
    etag = answer.header(b"etag")
    if etag is not None and status == 200 and etag in if_none_match(scope):
        status, body = 304, b""
        headers = [(n, v) for n, v in headers if n.lower() in _NOT_MODIFIED]
    elif answer.header(b"content-encoding") == b"gzip" and not _gzip(scope):
        body = gzip.decompress(body)
        headers = [
            (n, v)
            for n, v in headers
            if n.lower() not in (b"content-encoding", b"content-length")
        ]
        headers.append((b"content-length", str(len(body)).encode()))
    if how != "own":
        request_id = str(uuid.uuid4())
        duration_ms = (time.perf_counter() - started) * 1000
        timing = f"total;dur={duration_ms:.1f}, db;dur=0.0, cache;desc={how}"
        headers += [
            (b"x-request-id", request_id.encode()),
            (b"server-timing", timing.encode()),
        ]
        line = request_line(request_id, scope)
        log_answer(line, status, str(len(body)), duration_ms, how, 0.0)
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send(
        {
            "type": "http.response.body",
            "body": b"" if scope["method"] == "HEAD" else body,
        }
    )


def _gzip(scope: Scope) -> bool:
    """Whether the client takes gzip."""
    return any(n == b"accept-encoding" and b"gzip" in v for n, v in scope["headers"])

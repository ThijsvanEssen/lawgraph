"""Where the time of the current request goes: the statements it ran itself and the answers
of the cache it waited for.

The API opens one ``RequestTiming`` per request (``start``); the store adds the time of its
statements (``add_db``) and ``version_cache`` the answer it kept or computed (``hit``,
``miss``). A context variable, so the threads a request runs queries on inherit it; a
computation in the background (a thread of the cache's pool) has none and adds nothing.
"""

from __future__ import annotations

import contextvars
import dataclasses
import threading


@dataclasses.dataclass
class RequestTiming:
    """Seconds in statements the request ran itself, seconds it waited for a computation
    of the cache, and how many answers of the cache were kept (hits) or not (misses)."""

    db: float = 0.0
    waited: float = 0.0
    hits: int = 0
    misses: int = 0

    def __post_init__(self) -> None:
        self._lock = threading.Lock()

    @property
    def cache(self) -> str:
        """``hit`` when every answer of the cache was kept, ``miss`` when one was not,
        ``none`` when the request asked the cache nothing."""
        if self.misses:
            return "miss"
        return "hit" if self.hits else "none"


_current: contextvars.ContextVar[RequestTiming | None] = contextvars.ContextVar(
    "lawgraph_request_timing", default=None
)


def start() -> tuple[RequestTiming, contextvars.Token[RequestTiming | None]]:
    timing = RequestTiming()
    return timing, _current.set(timing)


def stop(token: contextvars.Token[RequestTiming | None]) -> None:
    _current.reset(token)


def add_db(seconds: float) -> None:
    if (timing := _current.get()) is not None:
        with timing._lock:
            timing.db += seconds


def hit() -> None:
    if (timing := _current.get()) is not None:
        with timing._lock:
            timing.hits += 1


def miss(waited: float) -> None:
    if (timing := _current.get()) is not None:
        with timing._lock:
            timing.misses += 1
            timing.waited += waited

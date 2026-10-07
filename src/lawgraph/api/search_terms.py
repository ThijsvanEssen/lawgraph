"""The terms of ``/api/search``, counted in this process and written to the day files of
``LAWGRAPH_SEARCH_STATS_DIR`` every ``FLUSH_SECONDS`` and when the API stops
(``core/search_stats.py``). Nothing of who asked is kept."""

from __future__ import annotations

import asyncio

from lawgraph.config.settings import SEARCH_STATS_DIR
from lawgraph.core.logging import get_logger
from lawgraph.core.search_stats import SearchTermCounter

logger = get_logger(__name__)

FLUSH_SECONDS = 900

COUNTER = SearchTermCounter()
_task: asyncio.Task[None] | None = None


def flush() -> None:
    """Write what was counted; a failure is logged and the counts of that flush are lost."""
    try:
        COUNTER.flush(SEARCH_STATS_DIR)
    except OSError as exc:
        logger.warning("Search terms not written: %s: %s", type(exc).__name__, exc)


async def _flush_every_while() -> None:
    while True:
        await asyncio.sleep(FLUSH_SECONDS)
        await asyncio.to_thread(flush)


async def start() -> None:
    global _task
    _task = asyncio.create_task(_flush_every_while())


async def stop() -> None:
    if _task is not None:
        _task.cancel()
    flush()

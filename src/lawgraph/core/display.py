"""How a long name is shortened for display: one rule for every node (pure functions)."""

from __future__ import annotations

# What is taken off the end of a shortened text before the ellipsis.
_TRAILING = " \t\n,;:–—-(/"


def shorten(text: str, limit: int) -> str:
    """*text* as it is when it fits in *limit* characters; else cut at the last word
    boundary before the limit, with an ellipsis: ``…het onvoorwaardelijk…``, never
    ``…het onvoorwaardelijk de``. A first word longer than half the limit is cut where
    the limit falls. The result is never longer than *limit*."""
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    space = cut.rfind(" ")
    if space > limit // 2:
        cut = cut[:space]
    return cut.rstrip(_TRAILING) + "…"

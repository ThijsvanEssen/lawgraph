"""Sitemaps (sitemaps.org 0.9): a plain XML file of at most ``MAX_URLS`` addresses per part
of a kind of page (about 3.5 MB, far below the 50 MB a part may be), and ``sitemap.xml``, the
index of them all. Not gzipped on disk: a search console read the gzipped parts as a file it
could not fetch (10 Oct), while Caddy compresses them on the way (``encode``).

``write`` puts each file in place whole (written beside it, then renamed), the index last,
and then removes the parts the index no longer names: a crawler never reads half a file or
an index naming a part that is not there.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from itertools import islice
from pathlib import Path
from xml.sax.saxutils import escape

MAX_URLS = 50_000
INDEX = "sitemap.xml"
_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"
_DAY = re.compile(r"\d{4}-\d{2}-\d{2}")
# a part, as it is written now (``.xml``) or was before (``.xml.gz``): those the index no
# longer names are removed
_PART = re.compile(r"sitemap-[a-z]+(-\d+)?\.xml(\.gz)?")


@dataclass(frozen=True)
class Entry:
    """A page: its readable address and the day it last changed (or None)."""

    path: str
    lastmod: str | None = None


def day(value: object, today: str) -> str | None:
    """The day (``YYYY-MM-DD``) a value of the graph begins with, or None; a day after
    *today* (a planned activity) is today."""
    text = value.strip()[:10] if isinstance(value, str) else ""
    return min(text, today) if _DAY.fullmatch(text) else None


def urlset(base: str, entries: Iterable[Entry]) -> bytes:
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', f'<urlset xmlns="{_NS}">']
    for entry in entries:
        lastmod = f"<lastmod>{entry.lastmod}</lastmod>" if entry.lastmod else ""
        lines.append(f"<url><loc>{escape(base + entry.path)}</loc>{lastmod}</url>")
    lines.append("</urlset>")
    return ("\n".join(lines) + "\n").encode("utf-8")


def sitemap_index(base: str, parts: Iterable[tuple[str, str | None]]) -> bytes:
    lines = ['<?xml version="1.0" encoding="UTF-8"?>', f'<sitemapindex xmlns="{_NS}">']
    for name, lastmod in parts:
        mod = f"<lastmod>{lastmod}</lastmod>" if lastmod else ""
        lines.append(f"<sitemap><loc>{escape(f'{base}/{name}')}</loc>{mod}</sitemap>")
    lines.append("</sitemapindex>")
    return ("\n".join(lines) + "\n").encode("utf-8")


def _chunks(entries: Iterable[Entry], size: int) -> Iterator[list[Entry]]:
    it = iter(entries)
    while chunk := list(islice(it, size)):
        yield chunk


def _put(path: Path, data: bytes) -> None:
    fresh = path.with_name(f".{path.name}.new")
    fresh.write_bytes(data)
    fresh.replace(path)


def write(
    out: Path,
    base: str,
    kinds: dict[str, Iterable[Entry]],
    *,
    max_urls: int = MAX_URLS,
) -> dict[str, int]:
    """Write the parts of each kind (``sitemap-<kind>.xml``; ``-<n>`` from the second part
    on) and the index into *out*; return the addresses per kind. A kind without addresses
    has no part."""
    out.mkdir(parents=True, exist_ok=True)
    parts: list[tuple[str, str | None]] = []
    counts: dict[str, int] = {}
    for kind, entries in kinds.items():
        counts[kind] = 0
        for n, chunk in enumerate(_chunks(entries, max_urls), start=1):
            name = f"sitemap-{kind}.xml" if n == 1 else f"sitemap-{kind}-{n}.xml"
            _put(out / name, urlset(base, chunk))
            days = [e.lastmod for e in chunk if e.lastmod]
            parts.append((name, max(days) if days else None))
            counts[kind] += len(chunk)
    _put(out / INDEX, sitemap_index(base, parts))
    named = {name for name, _ in parts}
    for stale in out.iterdir():
        if _PART.fullmatch(stale.name) and stale.name not in named:
            stale.unlink()
    return counts

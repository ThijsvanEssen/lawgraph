"""The shell of the front end (its built ``index.html``) with the head and the content of
one page: what a crawler reads without JavaScript, and what a visitor sees before the
app starts (it removes ``#seo`` and every ``[data-seo]`` but the title when it mounts).

The shell is read again whenever the file changes, so a release of the front end needs no
restart of the API. ``spa-routes.json`` beside it lists the pages of the app (path, title,
description): any other path that is no readable address is not found.
"""

from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any

from lawgraph.api.seo.pages import Page, full_title
from lawgraph.config import settings

# The shell when the front end is not there (a development API, a test without a build):
# the head and the content are all a page needs.
_BARE = (
    '<!doctype html>\n<html lang="nl">\n<head>\n<meta charset="utf-8" />\n</head>\n'
    '<body>\n<div style="display: contents"></div>\n</body>\n</html>\n'
)
_DESCRIPTION = re.compile(r"<meta\s[^>]*name=\"description\"[^>]*/?>\s*", re.I | re.S)
_TITLE = re.compile(r"<title[^>]*>.*?</title>\s*", re.I | re.S)
_APP = '<div style="display: contents">'


@dataclass(frozen=True)
class Shell:
    html: str
    # what changes with a release of the front end: part of every ETag
    stamp: str
    routes: dict[str, dict[str, Any]]


_lock = threading.Lock()
_kept: dict[str, Any] = {}


def shell() -> Shell:
    """The shell as the front end built it, read again when the file changed."""
    path = Path(settings.SPA_INDEX)
    try:
        stat = path.stat()
        stamp = f"{stat.st_mtime_ns}-{stat.st_size}"
    except OSError:
        stamp = "bare"
    with _lock:
        kept = _kept.get("shell")
        if kept is not None and kept.stamp == stamp:
            return kept
        if stamp == "bare":
            fresh = Shell(_BARE, stamp, {})
        else:
            fresh = Shell(path.read_text(encoding="utf-8"), stamp, _routes(path))
        _kept["shell"] = fresh
        return fresh


def _routes(index: Path) -> dict[str, dict[str, Any]]:
    """The pages of the app by path, from ``spa-routes.json`` beside the shell."""
    try:
        listed = json.loads((index.parent / "spa-routes.json").read_text("utf-8"))
    except (OSError, ValueError):
        return {}
    return {
        str(route["path"]).rstrip("/") or "/": route
        for route in listed
        if isinstance(route, dict) and route.get("path")
    }


def forget() -> None:
    """Read the shell again on the next page (the tests)."""
    with _lock:
        _kept.clear()


def _json_ld(page: Page, base: str) -> str:
    """The structured data of *page* and its breadcrumbs, as JSON-LD in a script."""
    graph: list[dict[str, Any]] = []
    if page.data:
        graph.append({**page.data, "url": base + page.path})
    if page.crumbs:
        graph.append(
            {
                "@type": "BreadcrumbList",
                "itemListElement": [
                    {
                        "@type": "ListItem",
                        "position": n,
                        "name": name,
                        "item": base + path,
                    }
                    for n, (name, path) in enumerate(
                        [("Concordans", "/"), *page.crumbs], start=1
                    )
                ],
            }
        )
    if not graph:
        return ""
    text = json.dumps(
        {"@context": "https://schema.org", "@graph": graph}, ensure_ascii=False
    )
    # no "</script>" inside the script
    return text.replace("</", "<\\/")


def _head(page: Page, base: str) -> str:
    url = base + page.path
    tags = [
        f"<title data-seo>{escape(page.title if page.whole_title else full_title(page.title))}"
        "</title>",
        f'<meta name="description" content="{escape(page.description)}" data-seo />',
    ]
    if page.path:
        tags.append(f'<link rel="canonical" href="{escape(url)}" data-seo />')
    if page.focus:
        tags.append(f'<meta name="focus" content="{escape(page.focus)}" data-seo />')
    if not page.index:
        tags.append('<meta name="robots" content="noindex" data-seo />')
    tags += [
        f'<meta property="og:title" content="{escape(page.title)}" data-seo />',
        f'<meta property="og:description" content="{escape(page.description)}" data-seo />',
    ]
    if page.path:
        tags.append(f'<meta property="og:url" content="{escape(url)}" data-seo />')
    if page.image:
        tags.append(
            f'<meta property="og:image" content="{escape(base + page.image)}" data-seo />'
        )
    data = _json_ld(page, base)
    if data:
        tags.append(f'<script type="application/ld+json" data-seo>{data}</script>')
    return "\n\t\t".join(tags)


def render(page: Page) -> str:
    """The shell with the head and the content of *page*."""
    base = settings.SITE_URL
    html = shell().html
    html = _DESCRIPTION.sub("", html, count=1)
    html = _TITLE.sub("", html, count=1)
    html = html.replace("</head>", f"\t{_head(page, base)}\n\t</head>", 1)
    if page.lang != "nl":
        html = re.sub(r'<html lang="[^"]*"', f'<html lang="{page.lang}"', html, count=1)
    if page.body:
        main = f'<main id="seo">{page.body}</main>\n\t\t'
        if _APP in html:
            html = html.replace(_APP, main + _APP, 1)
        else:
            html = re.sub(r"(<body[^>]*>)", lambda m: m[1] + main, html, count=1)
    return html


def stamp() -> str:
    """What the shell is at: part of the ETag of every page."""
    return shell().stamp


def route_of(path: str) -> dict[str, Any] | None:
    """The page of the app at *path* (``spa-routes.json``), or None."""
    return shell().routes.get(path.rstrip("/") or "/")


def indexed(route: dict[str, Any]) -> bool:
    """Whether a page of the app is for the search engines: all but those that say
    ``"index": false`` (a page with nothing of its own to find, as a reader's own maps
    kept in the browser)."""
    return route.get("index") is not False


def exists() -> bool:
    return os.path.exists(settings.SPA_INDEX)

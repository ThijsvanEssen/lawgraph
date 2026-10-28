"""The shell of the front end (its built ``index.html``) with the head and the content of
one page: what a crawler reads without JavaScript, and what a visitor sees before the
app starts (it removes ``#seo`` and every ``[data-seo]`` but the title when it mounts).

The shell is read again whenever the file changes, so a release of the front end needs no
restart of the API. ``spa-routes.json`` beside it lists the pages of the app (path, title,
description; a ``[param]`` in a path stands for any one segment): any other path that is
no readable address is not found. ``moved.json`` beside it maps the addresses that moved
(``/wetten``, the bare collection, to its list in the app) to where they are now: a 301.
``start.json`` beside it holds the fixed text of the start page, the one source of the app
and of ``/``. ``first-paint.js`` beside it paints a reader's address before the app has
come: the page holds the source as that script reads it, and the script after it.
"""

from __future__ import annotations

import json
import os
import re
import threading
from dataclasses import dataclass, field
from html import escape
from pathlib import Path
from typing import Any

from lawgraph.api.seo.pages.base import Page, crumbs_nav, full_title, organization
from lawgraph.config import settings
from lawgraph.core.logging import describe, get_logger

logger = get_logger(__name__)

# The shell when the front end is not there (a development API, a test without a build):
# the head and the content are all a page needs.
_BARE = (
    '<!doctype html>\n<html lang="nl">\n<head>\n<meta charset="utf-8" />\n</head>\n'
    '<body>\n<div style="display: contents"></div>\n</body>\n</html>\n'
)
_DESCRIPTION = re.compile(r"<meta\s[^>]*name=\"description\"[^>]*/?>\s*", re.I | re.S)
_TITLE = re.compile(r"<title[^>]*>.*?</title>\s*", re.I | re.S)
_APP = '<div style="display: contents">'
# a segment of a page's path that stands for any one segment (``/bundels/[id]``)
_PARAM = re.compile(r"\[\w+\]")


@dataclass(frozen=True)
class Shell:
    html: str
    # what changes with a release of the front end: part of every ETag
    stamp: str
    routes: dict[str, dict[str, Any]]
    # the fixed text of the start page (``start.json`` beside the shell), or empty
    start: dict[str, Any]
    # the addresses that moved, to where they are now (``moved.json``), or empty
    moved: dict[str, str]
    # the text of the prose pages (``spa-texts.json``): path to HTML, or empty
    texts: dict[str, str] = field(default_factory=dict)
    # the scripts of the first paint of a reader's address by the kind of its bron
    # (``first-paint-article.js``), the one for every kind under "" (``first-paint.js``)
    first_paint: dict[str, str] = field(default_factory=dict)


_lock = threading.Lock()
_kept: dict[str, Shell] = {}


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
            fresh = Shell(_BARE, stamp, {}, {}, {})
        else:
            fresh = Shell(
                path.read_text(encoding="utf-8"),
                stamp,
                _routes(path),
                _start(path),
                _moved(path),
                _texts(path),
                _first_paint(path),
            )
        _kept["shell"] = fresh
        return fresh


def _routes(index: Path) -> dict[str, dict[str, Any]]:
    """The pages of the app by path, from ``spa-routes.json`` beside the shell."""
    listed = _beside(index, "spa-routes.json", list)
    return {
        str(route["path"]).rstrip("/") or "/": route
        for route in listed or []
        if isinstance(route, dict) and route.get("path")
    }


def _start(index: Path) -> dict[str, Any]:
    """The fixed text of the start page, from ``start.json`` beside the shell."""
    return _beside(index, "start.json", dict) or {}


def _moved(index: Path) -> dict[str, str]:
    """The addresses that moved, from ``moved.json`` beside the shell: each path (without a
    trailing slash) to where it is now. A front end of before has none."""
    if not (index.parent / "moved.json").exists():
        return {}
    listed = _beside(index, "moved.json", dict) or {}
    return {
        str(path).rstrip("/"): to
        for path, to in listed.items()
        if isinstance(to, str) and to.startswith("/")
    }


def _texts(index: Path) -> dict[str, str]:
    """The text of the prose pages (``/over``, ``/privacy``), from ``spa-texts.json``
    beside the shell: each path (without a trailing slash) to its HTML. A front end of
    before has none."""
    if not (index.parent / "spa-texts.json").exists():
        return {}
    listed = _beside(index, "spa-texts.json", dict) or {}
    return {
        str(path).rstrip("/") or "/": html
        for path, html in listed.items()
        if isinstance(html, str) and html.strip()
    }


def _first_paint(index: Path) -> dict[str, str]:
    """The scripts that paint a reader's address before the app has come, beside the shell:
    one per kind of bron (``first-paint-judgment.js`` under ``judgment``), and the one that
    paints every kind (``first-paint.js``) under ""; a front end of before has none."""
    scripts: dict[str, str] = {}
    for file in sorted(index.parent.glob("first-paint*.js")):
        kind = file.stem.removeprefix("first-paint").removeprefix("-")
        try:
            scripts[kind] = file.read_text("utf-8")
        except OSError:
            continue
    return scripts


def _beside[T](index: Path, name: str, kind: type[T]) -> T | None:
    """The JSON file *name* the front end builds beside its shell, if it is a *kind*. One
    that is missing or does not read is a release of the front end that went wrong: logged
    with its path once (the shell is kept until it changes); the pages go on without it."""
    path = index.parent / name
    try:
        read = json.loads(path.read_text("utf-8"))
    except (OSError, ValueError) as exc:
        logger.error("The front end's %s does not read: %s", path, describe(exc))
        return None
    if not isinstance(read, kind):
        logger.error(
            "The front end's %s is no JSON %s but a %s.",
            path,
            kind.__name__,
            type(read).__name__,
        )
        return None
    return read


def forget() -> None:
    """Read the shell again on the next page (the tests)."""
    with _lock:
        _kept.clear()


def _json_ld(page: Page, base: str) -> str:
    """The structured data of *page* and its breadcrumbs, as JSON-LD in a script."""
    graph: list[dict[str, Any]] = []
    if page.data:
        graph.append({**page.data, "url": base + page.path})
    if page.organization:
        graph.append(organization(base))
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
    url = base + (page.canonical or page.path)
    title = page.title if page.whole_title else full_title(page.title)
    tags = [
        f"<title data-seo>{escape(title)}</title>",
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
    if page.citation:
        meta = {**page.citation, "citation_public_url": url}
        tags += [
            f'<meta name="{escape(name)}" content="{escape(value)}" data-seo />'
            for name, value in meta.items()
            if value
        ]
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
        main = (
            f'<main id="seo">{crumbs_nav(page.crumbs)}{page.body}</main>\n\t\t'
            + _paint(page)
        )
        if _APP in html:
            html = html.replace(_APP, main + _APP, 1)
        else:
            html = re.sub(r"(<body[^>]*>)", lambda m: m[1] + main, html, count=1)
    return html


def _paint(page: Page) -> str:
    """The source of *page* as the front end paints it first, and the script that paints
    it, after the content: it runs before the browser paints. Nothing for a page the front
    end does not paint first, or a front end without the script."""
    if page.first_paint is None:
        return ""
    scripts = shell().first_paint
    script = scripts.get(str(page.first_paint.get("kind", ""))) or scripts.get("")
    if not script:
        return ""
    data = json.dumps(page.first_paint, ensure_ascii=False).replace("</", "<\\/")
    return (
        f'<script type="application/json" id="first-paint-data">{data}</script>'
        f"<script>{script}</script>\n\t\t"
    )


def stamp() -> str:
    """What the shell is at: part of the ETag of every page."""
    return shell().stamp


def route_of(path: str) -> dict[str, Any] | None:
    """The page of the app at *path* (``spa-routes.json``): the one of that path, else the
    one whose pattern it fits; None for neither."""
    path = path.rstrip("/") or "/"
    routes = shell().routes
    found = routes.get(path)
    if found is not None:
        return found
    return next(
        (route for listed, route in routes.items() if _fits(path, listed)), None
    )


def _fits(path: str, listed: str) -> bool:
    """Whether *path* fits the pattern *listed*: as many segments, each the same or any
    one where *listed* has a ``[param]``."""
    if not is_pattern(listed):
        return False
    segments, pattern = path.split("/"), listed.split("/")
    return len(segments) == len(pattern) and all(
        seg == part or (bool(seg) and _PARAM.fullmatch(part) is not None)
        for seg, part in zip(segments, pattern, strict=True)
    )


def is_pattern(path: str) -> bool:
    """Whether the path of a page is a pattern (``/bundels/[id]``), no address itself."""
    return _PARAM.search(path) is not None


def indexed(route: dict[str, Any]) -> bool:
    """Whether a page of the app is for the search engines: all but those that say
    ``"index": false`` (a page with nothing of its own to find, as a reader's own bundels
    kept in the browser)."""
    return route.get("index") is not False


def exists() -> bool:
    return os.path.exists(settings.SPA_INDEX)

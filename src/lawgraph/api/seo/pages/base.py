"""What every page is made of: the page itself, its texts cut to what a search result
shows, and the pieces of its HTML."""

from __future__ import annotations

from dataclasses import dataclass, field
from html import escape
from typing import Any

from lawgraph.core.display import shorten
from lawgraph.core.dutch_dates import long_date
from lawgraph.core.names import text_of
from lawgraph.core.readable_paths import path_of
from lawgraph.core.xml import collapse_ws

SITE = "Concordans"
# The sources a list of a page links at most.
LINKS = 20
# The length a description is cut to: what a search result shows.
DESCRIPTION_MAX = 155
# The image of a page when it is shared (``og:image``, ``static/og`` of the front end) that
# has none of its own kind.
SITE_IMAGE = "/og/concordans.png"


@dataclass
class Page:
    """What the HTML of a source shows: its title (without the name of the site), its
    description, its canonical path, its breadcrumbs (name, path), its structured data,
    its content (HTML), whether it is indexed and its language."""

    title: str
    description: str
    path: str
    crumbs: list[tuple[str, str]] = field(default_factory=list)
    data: dict[str, Any] | None = None
    body: str = ""
    index: bool = True
    lang: str = "nl"
    # the image of the page when it is shared (``og:image``): one per kind
    image: str = SITE_IMAGE
    # whether ``title`` is the whole ``<title>`` already (a page of the app), without the
    # name of the site to add
    whole_title: bool = False
    # the node of the page (``<collection>/<key>``): the app opens it without a lookup
    focus: str = ""


def present(**fields: Any) -> dict[str, Any]:
    """The fields that have a value, in their order."""
    return {name: value for name, value in fields.items() if value}


def cut(text: str, length: int) -> str:
    """*text* in one line of at most *length* characters, cut at a word with an ellipsis."""
    return shorten(collapse_ws(text), length)


def full_title(title: str) -> str:
    """The ``<title>`` of a page: its title whole, then the site. Not cut: it is the title
    the app shows in its tab (``title`` of ``/api/nodes``), and a motion is found by every
    word of its subject (a search engine cuts what it shows itself)."""
    return f"{title}, {SITE}" if title else SITE


def period(start: Any, end: Any) -> str:
    """``sinds 2 juli 2024``, or ``2 juli 2024 tot 5 juli 2024``."""
    first, last = long_date(start), long_date(end)
    if first and last:
        return f"{first} tot {last}"
    return f"sinds {first}" if first else (f"tot {last}" if last else "")


def link(path: str | None, label: str) -> str:
    if not path:
        return escape(label)
    return f'<a href="{escape(path)}">{escape(label)}</a>'


def bullets(items: list[str]) -> str:
    return (
        "<ul>" + "".join(f"<li>{item}</li>" for item in items) + "</ul>"
        if items
        else ""
    )


def section(title: str, html: str) -> str:
    return f"<section><h2>{escape(title)}</h2>{html}</section>" if html else ""


def trail(
    parent: str, parent_path: str | None, title: str, path: str
) -> list[tuple[str, str]]:
    """The breadcrumbs of a page: its parent when it has a name and a page, then itself."""
    return ([(parent, parent_path)] if parent and parent_path else []) + [(title, path)]


def votes_list(voor: list[str], tegen: list[str]) -> str:
    """Who voted for, and who against."""
    return bullets([f"Voor: {escape(', '.join(voor))}"] if voor else []) + bullets(
        [f"Tegen: {escape(', '.join(tegen))}"] if tegen else []
    )


def member_link(row: dict[str, Any]) -> str:
    name = text_of(row.get("name"))
    return link(path_of(row["id"], {"slug": row.get("slug")}), name) if name else ""

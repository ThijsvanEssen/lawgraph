"""What every page is made of: the page itself, its texts cut to what a search result
shows, and the pieces of its HTML."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from html import escape
from typing import Any

from lawgraph.core.code_families import family_of
from lawgraph.core.display import shorten
from lawgraph.core.dossier_numbers import official_number
from lawgraph.core.dutch_dates import long_date
from lawgraph.core.models import parse_node_id
from lawgraph.core.names import (
    activity_title,
    article_name,
    case_title,
    commitment_title,
    document_title,
    joined,
    judgment_title,
    law_name,
    text_of,
)
from lawgraph.core.readable_paths import path_of
from lawgraph.core.xml import collapse_ws

SITE = "Concordans"
# The sources a list of a page links at most.
LINKS = 20
# The length a description is cut to: what a search result shows.
DESCRIPTION_MAX = 155
# The characters of the text of a judgment or a paper a page holds at most, cut after a
# whole paragraph: the whole text of 95 in 100 of them (lawgraph_small, 16 Oct: p95 96,000
# characters of a judgment, 99,000 of a paper with a text), a page of about 120 KB, 35 KB
# compressed. The rest is a link to the source away.
TEXT_MAX = 100_000
# The length a title of a commitment is cut to in a list.
LIST_TITLE_MAX = 160
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
    # the page a search engine finds instead (``rel="canonical"``), when not this one: the
    # page of the one motion a vote is about
    canonical: str = ""
    # what a reference manager reads (Zotero, Google Scholar): the ``citation_*`` and
    # ``DC.*`` meta tags of the page, name → content; its address (``citation_public_url``)
    # is added with them
    citation: dict[str, str] = field(default_factory=dict)
    # the source as the front end paints it before the app has come (its
    # ``lib/first-paint``): the fields of its API answer that paint reads, its kind in
    # ``kind``; None for a page the front end does not paint first
    first_paint: dict[str, Any] | None = None
    # whether the JSON-LD also names Concordans as an ``Organization`` (``/`` and ``/over``)
    organization: bool = False


def organization(base: str) -> dict[str, Any]:
    """Concordans as the publisher of the site, the one node of it in the JSON-LD (the
    ``WebSite`` of ``/`` points at it by ``@id``): what is certain, no more."""
    return {
        "@type": "Organization",
        "@id": f"{base}/#organization",
        "name": "Concordans",
        "url": f"{base}/",
        "logo": f"{base}/icon-512.png",
        "email": "concordans@tmve.nl",
    }


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


def capped(blocks: Iterable[tuple[str, str]], more: str = "") -> str:
    """The HTML of *blocks* (its HTML, its text) up to ``TEXT_MAX`` characters of text, each
    whole; *more* after them where the text goes on."""
    parts: list[str] = []
    used = 0
    for html, text in blocks:
        if parts and used + len(text) > TEXT_MAX:
            parts.append(more)
            break
        parts.append(html)
        used += len(text)
    return "".join(parts)


def lines(text: str) -> str:
    """*text* escaped, its lines kept."""
    return "<br>".join(escape(line) for line in text.split("\n") if line.strip())


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


def source_link(row: dict[str, Any]) -> str:
    """The link to a source a page names by its edges (``db/queries/seo_links.light``):
    its title as its own page has it, at its readable address; empty without one."""
    collection = row["collection"]
    name, path = _NAMED[collection](row)
    return link(path, name) if path and name else ""


def _document(row: dict[str, Any]) -> tuple[str, str | None]:
    light = row.get("light") or {}
    return document_title(row, light), path_of(row["id"], light)


def _judgment(row: dict[str, Any]) -> tuple[str, str | None]:
    light = row.get("light") or {}
    return judgment_title(light, row["id"]), path_of(row["id"], light)


def _article(row: dict[str, Any]) -> tuple[str, str | None]:
    # A book of a code is cited by its code (``Artikel 5:40 BW``), never by its own short
    # title (``BW5``).
    law = family_of(text_of(row.get("bwb_id"))) or text_of(row.get("law"))
    name = article_name(row.get("bwb_id"), text_of(row.get("article_number")), law)
    return name, path_of(row["id"], row)


def _law(row: dict[str, Any]) -> tuple[str, str | None]:
    props = row.get("props") or {}
    return law_name(props), path_of(row["id"], props)


def _member(row: dict[str, Any]) -> tuple[str, str | None]:
    return text_of(row.get("name")), path_of(row["id"], {"slug": row.get("slug")})


def _dossier(row: dict[str, Any]) -> tuple[str, str | None]:
    label = text_of(row.get("label"))
    name = joined(" ", f"Dossier {official_number(label)}", text_of(row.get("title")))
    return name, path_of(row["id"], {"label": label})


def _keyed(
    title: Callable[[dict[str, Any], str], str],
) -> Callable[[dict[str, Any]], tuple[str, str | None]]:
    """The name and address of a node titled by its props and key."""

    def named(row: dict[str, Any]) -> tuple[str, str | None]:
        props = row.get("props") or {}
        key = parse_node_id(row["id"])[1]
        return cut(title(props, key), LIST_TITLE_MAX), path_of(row["id"], props)

    return named


_NAMED: dict[str, Callable[[dict[str, Any]], tuple[str, str | None]]] = {
    "documents": _document,
    "judgments": _judgment,
    "articles": _article,
    "instruments": _law,
    "members": _member,
    "dossiers": _dossier,
    "cases": _keyed(case_title),
    "activities": _keyed(activity_title),
    "commitments": _keyed(commitment_title),
}


def source_links(rows: list[dict[str, Any]]) -> str:
    """``source_link`` of each of *rows*, as a list."""
    return bullets([item for item in map(source_link, rows) if item])


def crumbs_nav(crumbs: list[tuple[str, str]]) -> str:
    """The breadcrumbs of a page as its JSON-LD has them, readable: the site, then each
    crumb, the page itself last (without a link)."""
    if not crumbs:
        return ""
    items = [link("/", SITE)] + [link(path, name) for name, path in crumbs[:-1]]
    items.append(f'<span aria-current="page">{escape(crumbs[-1][0])}</span>')
    return (
        '<nav aria-label="Kruimelpad"><ol>'
        + "".join(f"<li>{item}</li>" for item in items)
        + "</ol></nav>"
    )

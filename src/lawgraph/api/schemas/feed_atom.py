"""A page of the feed as an Atom 1.0 document (``GET /api/feed.atom``)."""

from __future__ import annotations

import datetime as dt
from xml.etree import ElementTree

from lawgraph.api.schemas.feed import FeedItemDTO, FeedResponse
from lawgraph.config.constants import COLLECTION_INSTRUMENTS
from lawgraph.core.models import node_id
from lawgraph.core.readable_paths import path_of
from lawgraph.core.time import DUTCH_TIME

_ATOM = "http://www.w3.org/2005/Atom"


def _atom_entry(feed: ElementTree.Element, item: FeedItemDTO, site_url: str) -> None:
    entry = ElementTree.SubElement(feed, "entry")
    ElementTree.SubElement(entry, "id").text = f"tag:lawgraph,2026:{item.id}"
    ElementTree.SubElement(entry, "title").text = item.title or item.kind
    ElementTree.SubElement(entry, "updated").text = _dutch_day_start(item.date)
    # the event on Concordans, and its official page
    ElementTree.SubElement(
        entry, "link", rel="alternate", href=f"{site_url}{_page_of(item)}"
    )
    related = item.official_url or item.tk_url
    if related:
        ElementTree.SubElement(entry, "link", rel="related", href=related)
    ElementTree.SubElement(entry, "category", term=item.kind)
    for person in item.persons:
        author = ElementTree.SubElement(entry, "author")
        ElementTree.SubElement(author, "name").text = person.name or person.key or "-"
    lines = [line for line in (item.summary, _dossier_line(item)) if line]
    if lines:
        ElementTree.SubElement(entry, "summary").text = "\n".join(lines)


def _page_of(item: FeedItemDTO) -> str:
    """Where the event is on Concordans: its readable address; a version of a law, which
    has none of its own, the page of its law; a source without one (a paper the Kamer has
    not numbered) in the explorer."""
    law = item.commencement.instrument if item.commencement else None
    return (
        item.path
        or (path_of(node_id(COLLECTION_INSTRUMENTS, law.key)) if law else None)
        or f"/explore?focus={item.id}"
    )


def _dutch_day_start(day: str) -> str:
    """The start of *day* (``YYYY-MM-DD``) in the Netherlands: ``2026-05-12T00:00:00+02:00``."""
    start = dt.datetime.combine(dt.date.fromisoformat(day), dt.time(), DUTCH_TIME)
    return start.isoformat(timespec="seconds")


def _dossier_line(item: FeedItemDTO) -> str | None:
    if item.dossier is None:
        return None
    return " ".join(part for part in (item.dossier.number, item.dossier.title) if part)


def atom_feed(
    page: FeedResponse,
    *,
    title: str,
    self_url: str,
    next_url: str | None,
    page_url: str,
    site_url: str,
    updated: dt.datetime | None = None,
) -> bytes:
    """*page* as an Atom 1.0 document named *title*: its ``alternate`` link is *page_url*
    (the same view on Concordans, at *site_url*), each entry's the event there. The feed
    is *updated* when its events were last written, else on the day of its newest event;
    an entry on its day, the source giving no time of day: the start of that day in the
    Netherlands, with its offset."""
    feed = ElementTree.Element("feed", xmlns=_ATOM)
    ElementTree.SubElement(feed, "id").text = self_url
    ElementTree.SubElement(feed, "title").text = title
    newest = page.items[0].date if page.items else "1970-01-01"
    ElementTree.SubElement(feed, "updated").text = (
        updated.isoformat(timespec="seconds") if updated else _dutch_day_start(newest)
    )
    ElementTree.SubElement(feed, "link", rel="self", href=self_url)
    ElementTree.SubElement(feed, "link", rel="alternate", href=page_url)
    if next_url:
        ElementTree.SubElement(feed, "link", rel="next", href=next_url)
    for item in page.items:
        _atom_entry(feed, item, site_url)
    document: bytes = ElementTree.tostring(feed, encoding="utf-8", xml_declaration=True)
    return document

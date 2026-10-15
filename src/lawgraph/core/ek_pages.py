"""The pages of the Eerste Kamer's site that tell the changes in its composition.

``/personele_mutaties`` lists, per term, the news items about the members: an item is a date,
a headline (``Senator Van Gasteren uit BBB-fractie``) and a page of a few sentences. Of the
list the items and the terms before are read (``term_page``), of an item's page its text and
the members it links (``article``); ``core.ek_change_patterns`` reads the changes in them."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

# A day of an item: "11 juli 2023", "5 juli" (the year of the item).
from lawgraph.core.dutch_dates import DATE_YEAR_OPTIONAL as _DAY
from lawgraph.core.dutch_dates import dutch_day
from lawgraph.core.xml import html_text

_ITEM = re.compile(
    r'<a href="(/nieuws/\d{8}/[^"]+)">.*?<div>\s*(.*?)\s*</div>\s*</a>\s*'
    r"<span>([^<]+)</span>",
    re.S,
)
_TERM = re.compile(r'href="(/personele_mutaties\?zittingid=[a-z0-9]+)"')
_TERM_TITLE = re.compile(
    r"Personele mutaties (huidige zittingsperiode|zittingsperiode \d{4}-\d{4})"
)

# The list of changes of the current term; it links those of the terms before.
MUTATIONS_PATH = "/personele_mutaties"


@dataclass(frozen=True)
class Listed:
    """An item of ``/personele_mutaties``: its day, headline and page."""

    date: str
    headline: str
    path: str


@dataclass(frozen=True)
class TermPage:
    """A term of ``/personele_mutaties``: its title, its items, and the pages of the terms
    before it."""

    title: str
    items: list[Listed]
    terms: list[str]


def term_page(page: str) -> TermPage:
    """The items and the other terms of a page of ``/personele_mutaties``."""
    title = _TERM_TITLE.search(page)
    items = []
    for path, headline, day in _ITEM.findall(page):
        date = dutch_day(html_text(day, page=True))
        if date:
            items.append(
                Listed(date=date, headline=html_text(headline, page=True), path=path)
            )
    return TermPage(
        title=title.group(0) if title else "",
        items=items,
        terms=sorted(set(_TERM.findall(page))),
    )


@dataclass(frozen=True)
class Article:
    """The page of an item: its headline, its day, its text and the members it links."""

    headline: str
    date: str
    text: str
    persons: list[str] = field(default_factory=list)


def article(page: str, date: str, headline: str) -> Article:
    """The text of an item's page: what stands between its date and ``Terug naar boven``."""
    start = page.find("Nieuwsoverzicht")
    end = page.find("Terug naar boven", start)
    body = page[start:end] if start >= 0 and end > start else page
    text = html_text(body, page=True).removeprefix("Nieuwsoverzicht").strip()
    # the item's own date stands first: a day of the text is one after it
    text = re.sub(rf"^{_DAY}\s*", "", text)
    # the links to other items under it ("Lees ook: …") are not its text
    text = text.split("Lees ook:")[0].strip()
    return Article(
        headline=headline,
        date=date,
        text=text,
        persons=sorted(set(re.findall(r'href="(/persoon/[^"#?]+)"', body))),
    )

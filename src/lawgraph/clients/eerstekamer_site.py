"""Client for eerstekamer.nl: its list of votes on bills, its list of rejected bills, and
the pages of its factions and committees.

The Eerste Kamer publishes its votes only on its website; its terms allow reuse, also
commercial, with the source and the day it was taken over. ``robots.txt`` allows these
pages. The client asks for one page at a time, paced by the host's interval
(``HOST_MIN_INTERVAL``), and names Concordans in its ``User-Agent``. What the pages hold is
read by ``core.eerstekamer_votes``.
"""

from __future__ import annotations

from collections.abc import Iterator

from lawgraph.clients.base import BaseClient, response_text
from lawgraph.config.settings import EERSTEKAMER_SITE
from lawgraph.core import eerstekamer_composition, eerstekamer_votes
from lawgraph.core.logging import get_logger

logger = get_logger(__name__)

_USER_AGENT = "Concordans (https://github.com/ThijsvanEssen/lawgraph)"


class EerstekamerSiteClient(BaseClient):
    """Client for the lists of eerstekamer.nl."""

    def __init__(self, session=None) -> None:
        super().__init__(base_url=EERSTEKAMER_SITE, session=session)

    def url(self, path: str) -> str:
        return self._build_url(path)

    def vote_pages(self) -> Iterator[tuple[str, str]]:
        """``(url, html)`` of every page of the list of votes on bills, newest first; the
        caller stops when it has what it needs."""
        path: str | None = eerstekamer_votes.VOTES_PATH
        while path:
            url = self.url(path)
            page = self._page(url)
            yield url, page
            path = eerstekamer_votes.earlier_page(page)

    def rejected_pages(self) -> list[tuple[str, str]]:
        """``(url, html)`` of every page of the list of rejected bills."""
        pages: list[tuple[str, str]] = []
        seen: set[str] = set()
        path: str | None = eerstekamer_votes.REJECTED_PATH
        while path:
            seen.add(path)
            url = self.url(path)
            page = self._page(url)
            pages.append((url, page))
            path = eerstekamer_votes.next_rejected_page(page, seen)
        return pages

    def composition_pages(self) -> Iterator[tuple[str, str, str]]:
        """``(path, url, html)`` of the lists of factions and committees, of the page of
        every faction and committee they name, and of the plan of the hall (``Wie zit
        waar``)."""
        for path, entries in (
            (eerstekamer_composition.FACTIONS_PATH, eerstekamer_composition.factions),
            (
                eerstekamer_composition.COMMITTEES_PATH,
                eerstekamer_composition.committees,
            ),
        ):
            listing = self._page(self.url(path))
            yield path, self.url(path), listing
            for entry in entries(listing):
                yield entry.path, self.url(entry.path), self._page(self.url(entry.path))
        hall = eerstekamer_composition.HALL_PATH
        yield hall, self.url(hall), self._page(self.url(hall))

    def _page(self, url: str) -> str:
        response = self._get_raw_absolute_with_retry(
            url, timeout=60, headers={"User-Agent": _USER_AGENT}
        )
        return response_text(response)

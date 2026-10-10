"""Client for eerstekamer.nl: its list of votes on bills, its list of rejected bills, the
pages of its factions and committees, and the pages of its bills.

The Eerste Kamer publishes its votes only on its website; its terms allow reuse, also
commercial, with the source and the day it was taken over. ``robots.txt`` allows these
pages. The client asks for one page at a time, paced by the host's interval
(``HOST_MIN_INTERVAL``), and names Concordans in its ``User-Agent``. What the pages hold is
read by ``core.eerstekamer_votes``.
"""

from __future__ import annotations

from collections.abc import Container, Iterator

from lawgraph.clients.base import BaseClient, response_text
from lawgraph.config.settings import EERSTEKAMER_SITE
from lawgraph.core import (
    eerstekamer_bills,
    eerstekamer_composition,
    eerstekamer_votes,
    ek_changes,
)
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

    def listed_bills(self, *, older: bool) -> Iterator[eerstekamer_bills.ListedBill]:
        """The bills on the list of every committee (``/commissies``); with *older* also
        those on its pages of older bills (``verder``)."""
        committees = self._page(self.url(eerstekamer_composition.COMMITTEES_PATH))
        for committee in eerstekamer_composition.committees(committees):
            for path in eerstekamer_bills.bill_lists(
                self._page(self.url(committee.path))
            ):
                next_path: str | None = path
                while next_path:
                    bills, following = eerstekamer_bills.listed_bills(
                        self._page(self.url(next_path))
                    )
                    yield from bills
                    next_path = following if older else None

    def mutation_terms(
        self, stored: Container[str] = ()
    ) -> Iterator[tuple[str, str, str]]:
        """``(path, url, html)`` of the list of changes of the current term
        (``/personele_mutaties``), and of each earlier term it links that is not in
        *stored*: the list of a term that ended does not change."""
        url = self.url(ek_changes.MUTATIONS_PATH)
        current = self._page(url)
        yield ek_changes.MUTATIONS_PATH, url, current
        for path in ek_changes.term_page(current).terms:
            if path in stored:
                continue
            url = self.url(path)
            yield path, url, self._page(url)

    def bill_page(self, path: str) -> tuple[str, str]:
        """``(url, html)`` of the page of a bill."""
        url = self.url(path)
        return url, self._page(url)

    def page_at(self, path: str) -> tuple[str, str]:
        """``(path, html)`` of a page, *path* the one it was served at after a redirect
        (``/menukeuze_plenair`` forwards to the next plenary sitting)."""
        response = self._get_raw_absolute_with_retry(
            self.url(path), timeout=60, headers={"User-Agent": _USER_AGENT}
        )
        served = response.url or self.url(path)
        site = self.url("/").rstrip("/")
        return served[len(site) :] if served.startswith(site) else path, response_text(
            response
        )

    def _page(self, url: str) -> str:
        response = self._get_raw_absolute_with_retry(
            url, timeout=60, headers={"User-Agent": _USER_AGENT}
        )
        return response_text(response)

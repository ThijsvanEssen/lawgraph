from __future__ import annotations

import datetime as dt
from collections.abc import Iterator, Sequence
from typing import Any

import requests

from lawgraph.clients.base import BaseClient
from lawgraph.config.sources import RECHTSPRAAK
from lawgraph.core.logging import get_logger
from lawgraph.core.rechtspraak_index import IndexEntry, parse_index

logger = get_logger(__name__)

OWMS_TERMS = "http://standaarden.overheid.nl/owms/terms/"
# Every court an ECLI can name: code, official name, Type and days (``core.court_sources``).
INSTANTIES_LIST = "Waardelijst/Instanties"
INDEX_PAGE_SIZE = 1000


class RechtspraakClient(BaseClient):
    """Client for the open data of the Rechtspraak
    (https://www.rechtspraak.nl/Uitspraken/Paginas/Open-Data.aspx)."""

    def __init__(self, session: requests.Session | None = None) -> None:
        super().__init__(base_url=RECHTSPRAAK.base_url, session=session)

    def instanties(self) -> tuple[str, str]:
        """``(url, xml)`` of the Instanties value list. Raises when it lists no court."""
        xml = self.get_text(INSTANTIES_LIST)
        if "<Instantie>" not in xml:
            raise RuntimeError(
                f"{INSTANTIES_LIST} lists no court: the list has changed."
            )
        return self._build_url(INSTANTIES_LIST), xml

    def iter_index(
        self,
        *,
        courts: Sequence[str] = (),
        date_from: dt.date | None = None,
        date_to: dt.date | None = None,
        modified_from: dt.datetime | None = None,
        page_size: int = INDEX_PAGE_SIZE,
    ) -> Iterator[IndexEntry]:
        """Yield the judgments of *courts* (OWMS terms; none: of every court), page by page.

        With *date_from* only the judgments decided from that date to *date_to* (default
        today); with *modified_from* those published or changed since then. For a long
        window ``modified`` is no filter (the Rechtspraak republished nearly its whole
        corpus); for a short one it is what finds a judgment published long after its
        decision. A page that is not XML raises.
        """
        params: dict[str, Any] = {
            "type": "Uitspraak",
            "return": "DOC",
            "max": str(page_size),
        }
        if courts:
            params["creator"] = [OWMS_TERMS + court for court in courts]
        if date_from is not None:
            params["date"] = [
                date_from.isoformat(),
                (date_to or dt.date.today()).isoformat(),
            ]
        if modified_from is not None:
            # Published or changed since then, whenever it was decided.
            now = dt.datetime.now(dt.UTC)
            params["modified"] = [
                modified_from.strftime("%Y-%m-%dT%H:%M:%S"),
                now.strftime("%Y-%m-%dT%H:%M:%S"),
            ]
        start = 0
        fetched = 0
        total: int | None = None
        while True:
            params["from"] = str(start)
            logger.debug("Rechtspraak index from=%d", start)
            page_total, entries = parse_index(
                self.get_text("uitspraken/zoeken", params=params)
            )
            if total is None:
                total = page_total
            fetched += len(entries)
            yield from entries
            if len(entries) < page_size:
                break
            start += page_size
        if total is not None and fetched != total:
            logger.warning(
                "Rechtspraak index: %d entries read, the search matched %d; "
                "the index changed while it was read.",
                fetched,
                total,
            )

    def fetch_ecli_content(self, ecli: str) -> str:
        """The XML of the judgment *ecli*; a page that is not XML raises
        (``UnexpectedAnswer``)."""
        logger.debug("Fetching Rechtspraak content for %s", ecli)
        return self.get_xml("uitspraken/content", params={"id": ecli})

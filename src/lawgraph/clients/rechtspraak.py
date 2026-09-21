from __future__ import annotations

import datetime as dt
from collections.abc import Iterator, Sequence
from typing import Any

from lawgraph.clients.base import BaseClient
from lawgraph.config.settings import RECHTSPRAAK_BASE_URL
from lawgraph.core.judgments import IndexEntry, parse_index
from lawgraph.core.logging import get_logger

logger = get_logger(__name__)

OWMS_TERMS = "http://standaarden.overheid.nl/owms/terms/"
INDEX_PAGE_SIZE = 1000


class RechtspraakClient(BaseClient):
    """
    Client voor de RESTful webservice van de Rechtspraak.

    Docs:
      - https://www.rechtspraak.nl/Uitspraken/Paginas/Open-Data.aspx
    """

    def __init__(self, session=None) -> None:
        """Set up the Rechtspraak API client with optional session injection."""
        super().__init__(
            base_url=RECHTSPRAAK_BASE_URL,
            session=session,
        )

    def iter_index(
        self,
        *,
        courts: Sequence[str],
        date_from: dt.date | None = None,
        date_to: dt.date | None = None,
        modified_from: dt.datetime | None = None,
        page_size: int = INDEX_PAGE_SIZE,
    ) -> Iterator[IndexEntry]:
        """Yield the judgments of *courts* (OWMS terms), page by page.

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
            "creator": [OWMS_TERMS + court for court in courts],
        }
        if date_from is not None:
            params["date"] = [
                date_from.isoformat(),
                (date_to or dt.date.today()).isoformat(),
            ]
        if modified_from is not None:
            # Published or changed since then, whenever it was decided.
            now = dt.datetime.now(dt.timezone.utc)
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
                self._get_text("uitspraken/zoeken", params=params)
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
        """Retrieve the XML content for a single Rechtspraak ECLI."""
        logger.debug("Fetching Rechtspraak content for %s", ecli)
        return self._get_text("uitspraken/content", params={"id": ecli})

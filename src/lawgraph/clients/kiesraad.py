"""Client for the Kiesraad's databank of election results (verkiezingsuitslagen.nl): the page
of an election, whose data ``core.kiesraad`` reads. One page at a time, paced by the host's
interval."""

from __future__ import annotations

import requests

from lawgraph.clients.base import PAGE_TIMEOUT, BaseClient
from lawgraph.config.sources import KIESRAAD


class KiesraadClient(BaseClient):
    """Client for the pages of the Kiesraad's databank."""

    def __init__(self, session: requests.Session | None = None) -> None:
        super().__init__(base_url=KIESRAAD.base_url, session=session)

    def election(self, code: str) -> tuple[str, str]:
        """``(url, html)`` of the page of the election *code* (``EK20230530``)."""
        url = self._build_url(f"verkiezingen/detail/{code}")
        return url, self.get_text(url, timeout=PAGE_TIMEOUT)

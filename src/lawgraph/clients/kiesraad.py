"""Client for the Kiesraad's databank of election results (verkiezingsuitslagen.nl): the page
of an election, whose data ``core.kiesraad`` reads. One page at a time, paced by the host's
interval, Concordans named in its ``User-Agent``."""

from __future__ import annotations

from lawgraph.clients.base import BaseClient, response_text
from lawgraph.core.kiesraad import DATABANK

_USER_AGENT = "Concordans (https://github.com/ThijsvanEssen/lawgraph)"
SITE = "https://www.verkiezingsuitslagen.nl"


class KiesraadClient(BaseClient):
    """Client for the pages of the Kiesraad's databank."""

    def __init__(self, session=None) -> None:
        super().__init__(base_url=SITE, session=session)

    def election(self, code: str) -> tuple[str, str]:
        """``(url, html)`` of the page of the election *code* (``EK20230530``)."""
        url = DATABANK.format(code=code)
        response = self._get_raw_absolute_with_retry(
            url, timeout=60, headers={"User-Agent": _USER_AGENT}
        )
        return url, response_text(response)

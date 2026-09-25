"""Client for rijksoverheid.nl: the pages of the cabinets since 1945.

``/regering/over-de-regering/kabinetten-sinds-1945`` links one page per cabinet
(``…/kabinetten-sinds-1945/kabinet-schoof``). Rijksoverheid publishes them under CC0. The
client asks for one page at a time, paced by the host's interval (``HOST_MIN_INTERVAL``), and
names Concordans in its ``User-Agent``.
"""

from __future__ import annotations

import re

from lawgraph.clients.base import BaseClient, response_text
from lawgraph.config.settings import RIJKSOVERHEID_BASE
from lawgraph.core.logging import get_logger

logger = get_logger(__name__)

CABINETS_PATH = "/regering/over-de-regering/kabinetten-sinds-1945"
_USER_AGENT = "Concordans (https://github.com/ThijsvanEssen/lawgraph)"


def cabinet_slugs(index: str) -> list[str]:
    """The slugs of the cabinet pages the index links, each once, in order."""
    found = re.findall(rf'href="{CABINETS_PATH}/([a-z0-9-]+)"', index)
    return list(dict.fromkeys(found))


class RijksoverheidClient(BaseClient):
    """Client for the cabinet pages of rijksoverheid.nl."""

    def __init__(self, session=None) -> None:
        super().__init__(base_url=RIJKSOVERHEID_BASE, session=session)

    def url(self, slug: str | None = None) -> str:
        return self._build_url(f"{CABINETS_PATH}/{slug}" if slug else CABINETS_PATH)

    def cabinet_slugs(self) -> list[str]:
        """Every cabinet the index links. Raises when it links none: the site changed."""
        slugs = cabinet_slugs(self._page(self.url()))
        if not slugs:
            raise RuntimeError(
                f"{self.url()} links no cabinet page: the site has changed."
            )
        logger.info("Rijksoverheid: %d cabinet pages.", len(slugs))
        return slugs

    def cabinet_page(self, slug: str) -> str:
        return self._page(self.url(slug))

    def _page(self, url: str) -> str:
        response = self._get_raw_absolute_with_retry(
            url, timeout=60, headers={"User-Agent": _USER_AGENT}
        )
        return response_text(response)

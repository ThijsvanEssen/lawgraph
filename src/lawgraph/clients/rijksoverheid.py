"""Client for rijksoverheid.nl: the pages of the cabinets since 1945.

``/regering/over-de-regering/kabinetten-sinds-1945`` links one page per cabinet
(``…/kabinetten-sinds-1945/kabinet-schoof``). Rijksoverheid publishes them under CC0. The
client asks for one page at a time, paced by the host's interval (``config/sources.py``).
"""

from __future__ import annotations

import re

from lawgraph.clients.base import PAGE_TIMEOUT, BaseClient
from lawgraph.config.sources import RIJKSOVERHEID
from lawgraph.core.logging import get_logger

logger = get_logger(__name__)

CABINETS_PATH = "/regering/over-de-regering/kabinetten-sinds-1945"


def cabinet_slugs(index: str) -> list[str]:
    """The slugs of the cabinet pages the index links, each once, in order."""
    found = re.findall(rf'href="{CABINETS_PATH}/([a-z0-9-]+)"', index)
    return list(dict.fromkeys(found))


class RijksoverheidClient(BaseClient):
    """Client for the cabinet pages of rijksoverheid.nl."""

    def __init__(self, session=None) -> None:
        super().__init__(base_url=RIJKSOVERHEID.base_url, session=session)

    def url(self, slug: str | None = None) -> str:
        return self._build_url(f"{CABINETS_PATH}/{slug}" if slug else CABINETS_PATH)

    def cabinet_slugs(self) -> list[str]:
        """Every cabinet the index links. Raises when it links none: the site changed."""
        slugs = cabinet_slugs(self.get_text(self.url(), timeout=PAGE_TIMEOUT))
        if not slugs:
            raise RuntimeError(
                f"{self.url()} links no cabinet page: the site has changed."
            )
        logger.info("Rijksoverheid: %d cabinet pages.", len(slugs))
        return slugs

    def cabinet_page(self, slug: str) -> str:
        return self.get_text(self.url(slug), timeout=PAGE_TIMEOUT)

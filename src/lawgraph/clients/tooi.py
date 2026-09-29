"""Client for TOOI (standaarden.overheid.nl): the value list of every ministry.

KOOP publishes ``rwc_ministeries_compleet``, every ministry since about 2010 with its names,
dates and the events between them, in numbered versions. The page of the list links each
version (``…/rwc_ministeries_compleet/6``); a version answers JSON-LD. The content of the
TOOI registers and value lists "mag zonder beperkingen door eenieder gebruikt worden"
(TOOI beheerplan, 2.3 Rechtenbeleid).
"""

from __future__ import annotations

import re
from typing import Any

from lawgraph.clients.base import BaseClient
from lawgraph.config.settings import TOOI_BASE
from lawgraph.core.logging import get_logger

logger = get_logger(__name__)

MINISTRIES_LIST = "tooi/set/rwc_ministeries_compleet"
_USER_AGENT = "Concordans (https://github.com/ThijsvanEssen/lawgraph)"


def latest_version(page: str) -> int | None:
    """The highest version the page of a value list links."""
    found = re.findall(r"rwc_ministeries_compleet%2F(\d+)", page)
    return max(map(int, found)) if found else None


class TooiClient(BaseClient):
    """Client for the TOOI value lists."""

    def __init__(self, session=None) -> None:
        super().__init__(base_url=TOOI_BASE, session=session)

    def ministries(self) -> tuple[str, list[dict[str, Any]]]:
        """``(url, items)`` of the latest version of the ministries list. Raises when the
        page links no version or the version holds no ministry."""
        page = self._get_raw_absolute_with_retry(
            self._build_url(MINISTRIES_LIST), headers={"User-Agent": _USER_AGENT}
        ).text
        version = latest_version(page)
        if version is None:
            raise RuntimeError(
                f"{MINISTRIES_LIST} links no version: the site has changed."
            )
        url = self._build_url(f"{MINISTRIES_LIST}/{version}")
        items = self._get_raw_absolute_with_retry(
            url,
            headers={"User-Agent": _USER_AGENT, "Accept": "application/ld+json"},
        ).json()
        if not any("Ministerie" in str(i.get("@type")) for i in items):
            raise RuntimeError(f"{url} holds no ministry: the list has changed.")
        logger.info(
            "TOOI: version %d of the ministries list, %d items.", version, len(items)
        )
        return url, items

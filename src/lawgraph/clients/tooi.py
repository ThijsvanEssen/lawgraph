"""Client for TOOI (standaarden.overheid.nl): the value list of every ministry, and the
thesauri of the BWB.

KOOP publishes ``rwc_ministeries_compleet``, every ministry since about 2010 with its names,
dates and the events between them, and ``scw_bwb_rechtsgebieden`` and ``scw_bwb_themas``, the
legal areas and the government themes a regulation of the BWB is filed under (its WTI), as
SKOS concepts with their ``broader`` concept. Each list comes in numbered versions. The page
of the list links each version (``…/rwc_ministeries_compleet/6``); a version answers JSON-LD.
The content of the TOOI registers and value lists "mag zonder beperkingen door eenieder
gebruikt worden" (TOOI beheerplan, 2.3 Rechtenbeleid).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from lawgraph.clients.base import BaseClient
from lawgraph.config.constants import TOOI_BWB_LEGAL_AREAS, TOOI_BWB_THEMES
from lawgraph.config.sources import TOOI
from lawgraph.core.bwb_wti import SKOS_PREF_LABEL
from lawgraph.core.logging import get_logger

logger = get_logger(__name__)

MINISTRIES_LIST = "tooi/set/rwc_ministeries_compleet"
LEGAL_AREAS_LIST = f"tooi/set/{TOOI_BWB_LEGAL_AREAS}"
THEMES_LIST = f"tooi/set/{TOOI_BWB_THEMES}"


def latest_version(page: str, value_list: str = MINISTRIES_LIST) -> int | None:
    """The highest version the page of *value_list* links."""
    name = re.escape(value_list.rsplit("/", 1)[-1])
    found = re.findall(rf"{name}%2F(\d+)", page)
    return max(map(int, found)) if found else None


class TooiClient(BaseClient):
    """Client for the TOOI value lists."""

    def __init__(self, session=None) -> None:
        super().__init__(base_url=TOOI.base_url, session=session)

    def ministries(self) -> tuple[str, list[dict[str, Any]]]:
        """``(url, items)`` of the latest version of the ministries list. Raises when the
        page links no version or the version holds no ministry."""
        return self._latest(
            MINISTRIES_LIST,
            lambda item: "Ministerie" in str(item.get("@type")),
            "ministry",
        )

    def thesaurus(self, value_list: str) -> tuple[str, list[dict[str, Any]]]:
        """``(url, items)`` of the latest version of a thesaurus of the BWB
        (``LEGAL_AREAS_LIST``, ``THEMES_LIST``). Raises when the page links no version or
        the version holds no concept."""
        return self._latest(value_list, lambda item: SKOS_PREF_LABEL in item, "concept")

    def _latest(
        self, value_list: str, holds: Callable[[dict[str, Any]], bool], what: str
    ) -> tuple[str, list[dict[str, Any]]]:
        """``(url, items)`` of the latest version of *value_list*, when an item *holds* a
        *what*."""
        version = latest_version(self.get_text(value_list), value_list)
        if version is None:
            raise RuntimeError(f"{value_list} links no version: the site has changed.")
        url = self._build_url(f"{value_list}/{version}")
        items = self.get_json(url, headers={"Accept": "application/ld+json"})
        if not any(holds(item) for item in items):
            raise RuntimeError(f"{url} holds no {what}: the list has changed.")
        logger.info(
            "TOOI: version %d of %s, %d items.", version, value_list, len(items)
        )
        return url, items

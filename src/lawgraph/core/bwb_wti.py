"""BWB WTI (wetstechnische informatie): the official abbreviations of a regulation.

A WTI file opens with one ``<algemene-informatie>`` element; the amendment log and the
related regulations that follow make the file large (27 MB for the Wetboek van Strafrecht).
Only that first element is kept. Its ``<afkortingen>`` list is sorted alphabetically by the
source, so the position of an abbreviation says nothing about its importance.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from collections import Counter
from collections.abc import Mapping, Sequence

from lawgraph.config.constants import CODE_FAMILIES
from lawgraph.core.xml import collapse_ws, iter_named

GENERAL_INFO_START = "<algemene-informatie"
GENERAL_INFO_END = "</algemene-informatie>"


def extract_general_info(wti_head: str) -> str | None:
    """The ``<algemene-informatie>`` element, verbatim, from the start of a WTI file.

    *wti_head* may stop anywhere after the closing tag. ``None`` when the element is
    missing or not yet complete.
    """
    start = wti_head.find(GENERAL_INFO_START)
    end = wti_head.find(GENERAL_INFO_END, start)
    if start < 0 or end < 0:
        return None
    return wti_head[start : end + len(GENERAL_INFO_END)]


def parse_abbreviations(general_info_xml: str) -> list[str]:
    """The ``<afkorting>`` values in source order, without case-insensitive repeats.

    The source lists ``GW`` and ``Gw`` as two abbreviations; citations are matched without
    regard to case, so the first spelling is kept. Raises ``ET.ParseError`` on broken XML.
    """
    root = ET.fromstring(general_info_xml)
    abbreviations: list[str] = []
    seen: set[str] = set()
    for element in iter_named(root, "afkorting"):
        value = collapse_ws(element.text)
        if value and value.upper() not in seen:
            seen.add(value.upper())
            abbreviations.append(value)
    return abbreviations


def choose_short_titles(
    abbreviations_by_id: Mapping[str, Sequence[str]],
) -> dict[str, str | None]:
    """Pick the one abbreviation per regulation that becomes its ``short_title``.

    A short title has to lead back to one regulation, so an abbreviation that several
    regulations claim never wins, and neither does a code whose books are regulations of
    their own (``CODE_FAMILIES``: every book of the Burgerlijk Wetboek lists ``BW``, also
    when only one book is loaded). Of the remaining ones the shortest wins (``Sr`` over
    ``WvS`` and ``WvSr``, ``WVW`` over ``WVW 1994``, ``BW1`` over ``BW Boek 1``); equal
    lengths keep the source order.
    A regulation left with nothing gets ``None``. Comparison ignores case.
    """
    claims = Counter(
        claimed
        for abbreviations in abbreviations_by_id.values()
        for claimed in {abbreviation.upper() for abbreviation in abbreviations}
    )
    chosen: dict[str, str | None] = {}
    for regulation_id, abbreviations in abbreviations_by_id.items():
        own = [
            a
            for a in abbreviations
            if claims[a.upper()] == 1 and a.upper() not in CODE_FAMILIES
        ]
        chosen[regulation_id] = min(own, key=len) if own else None
    return chosen

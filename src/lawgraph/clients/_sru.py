"""Shared SRU record parsing for KOOP publication clients."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

from lawgraph.core.xml import find_own_text, local_name


def parse_sru_records(
    root: ET.Element,
    *,
    id_pattern: re.Pattern[str],
    extra_fields: tuple[str, ...] = (),
    default_title_prefix: str = "Publicatie",
) -> list[dict[str, Any]]:
    """Parse SRU response XML into record dicts.

    Each record gets at minimum: identifier, year, number, title, content_url.
    Pass extra field local names via ``extra_fields`` to pull in additional
    single-valued elements (e.g. ``("date",)`` for Staatscourant records).
    """
    records: list[dict[str, Any]] = []

    for record_elem in root.iter():
        if local_name(record_elem.tag) != "record":
            continue

        identifier = find_own_text(record_elem, "identifier") or find_own_text(
            record_elem, "recordIdentifier"
        )
        if not identifier:
            continue

        m = id_pattern.search(identifier)
        if not m:
            continue

        year = m.group(1)
        number = m.group(2)
        title = (
            find_own_text(record_elem, "title")
            or f"{default_title_prefix} {year}/{number}"
        )
        content_url = find_own_text(record_elem, "contentURL")

        record: dict[str, Any] = {
            "identifier": identifier,
            "year": year,
            "number": number,
            "title": title,
            "content_url": content_url,
        }
        for field_name in extra_fields:
            record[field_name] = find_own_text(record_elem, field_name)

        records.append(record)

    return records

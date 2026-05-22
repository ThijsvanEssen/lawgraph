"""Shared SRU record parsing for KOOP publication clients."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

_NS_STRIP = re.compile(r"\{[^}]+\}")


def _local_name(tag: str) -> str:
    return _NS_STRIP.sub("", tag)


def _find_text(elem: ET.Element, local_name: str) -> str | None:
    for child in elem.iter():
        if _local_name(child.tag) == local_name:
            return (child.text or "").strip() or None
    return None


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
        if _local_name(record_elem.tag) != "record":
            continue

        identifier = _find_text(record_elem, "identifier") or _find_text(
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
            _find_text(record_elem, "title")
            or f"{default_title_prefix} {year}/{number}"
        )
        content_url = _find_text(record_elem, "contentURL")

        record: dict[str, Any] = {
            "identifier": identifier,
            "year": year,
            "number": number,
            "title": title,
            "content_url": content_url,
        }
        for field_name in extra_fields:
            record[field_name] = _find_text(record_elem, field_name)

        records.append(record)

    return records

"""Shared SRU record parsing for KOOP publication clients."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from typing import Any

import requests

from lawgraph.clients.base import BaseClient
from lawgraph.core.logging import get_logger
from lawgraph.core.xml import find_own_text, local_name

logger = get_logger(__name__)

_IDENTIFIER_RE = re.compile(r"[\w.-]+")


def raise_on_diagnostic(root: ET.Element, *, context: str) -> None:
    """Raise when an SRU response is a ``<diagnostic>`` error, not a result page.

    Without this an unsupported index or a bad query looks like a search with no results.
    """
    for element in root.iter():
        if local_name(element.tag) == "diagnostic":
            message = next(
                (
                    (child.text or "").strip()
                    for child in element.iter()
                    if local_name(child.tag) == "message"
                ),
                "unknown SRU error",
            )
            raise RuntimeError(f"SRU error ({context}): {message}")


def parse_sru_records(
    root: ET.Element,
    *,
    id_pattern: re.Pattern[str],
    extra_fields: tuple[str, ...] = (),
    default_title_prefix: str = "Publicatie",
) -> list[dict[str, Any]]:
    """Parse SRU response XML into record dicts.

    Each record gets at minimum: identifier, year, number, title, content_url (the ``url`` of
    the record: its XML in the repository).
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
        content_url = find_own_text(record_elem, "url")

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


def fetch_publication_xml(
    client: BaseClient, kind: str, id_pattern: re.Pattern[str], identifier: str
) -> str | None:
    """The XML of a publication (``stb``, ``stcrt``) from the repository.

    ``None`` when the identifier is malformed or the repository has no XML for it (404); any
    other failure raises, after the retries of ``BaseClient``.
    """
    if not id_pattern.search(identifier) or not _IDENTIFIER_RE.fullmatch(identifier):
        logger.warning("Cannot parse %s identifier: %s", kind, identifier)
        return None
    year = identifier.split("-")[1]
    url = (
        f"{client.base_url.rstrip('/')}/frbr/officielepublicaties/{kind}/{year}/"
        f"{identifier}/1/xml/{identifier}.xml"
    )
    try:
        return client._get_raw_absolute_with_retry(url, timeout=60).text
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            logger.debug("%s XML not found at %s (404)", kind, url)
            return None
        raise

"""Shared SRU record parsing for KOOP publication clients."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator
from typing import Any

import requests

from lawgraph.clients.base import BaseClient, response_text
from lawgraph.core.logging import get_logger
from lawgraph.core.xml import find_own_text, local_name

logger = get_logger(__name__)

_IDENTIFIER_RE = re.compile(r"[\w.-]+")

SRU_PAGE_SIZE = 100


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


def number_of_records(root: ET.Element) -> int:
    """The total the service reports for the query (``numberOfRecords``)."""
    for element in root.iter():
        if local_name(element.tag) == "numberOfRecords":
            return int((element.text or "0").strip())
    return 0


def record_identifier(record: ET.Element) -> str | None:
    """The ``dcterms:identifier`` of one ``<record>``."""
    return find_own_text(record, "identifier") or find_own_text(
        record, "recordIdentifier"
    )


def parse_record_fields(
    record: ET.Element, fields: dict[str, str]
) -> dict[str, str | None]:
    """``{name: text}`` of the single-valued elements of one record, by local element name."""
    return {name: find_own_text(record, element) for name, element in fields.items()}


def iter_publications(
    client: BaseClient,
    endpoint: str,
    *,
    query: str,
    parse: Callable[[ET.Element], list[dict[str, Any]]],
    context: str,
    page_size: int = SRU_PAGE_SIZE,
    connection: str | None = "ob",
    limit: int | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield every record of *query*, page by page, each page turned into dicts by *parse*.

    The service answers HTTP 504 for every record from position 10000 on, so a result is
    not paged by ``startRecord`` but by key: each page asks for the identifiers after the
    last one of the previous page, sorted by identifier. When the records are used up the
    pages must add up to the total the service reports; otherwise this raises. *limit* stops
    early (and skips that check). A failing request or an SRU diagnostic raises, after the
    records of the earlier pages were yielded.
    """
    yielded = 0
    fetched = 0
    total: int | None = None
    last: str | None = None
    while True:
        after = "" if last is None else f' AND dt.identifier>"{last}"'
        params = {
            "operation": "searchRetrieve",
            "version": "1.2",
            "query": f"{query}{after} sortBy dt.identifier/sort.ascending",
            "maximumRecords": str(page_size),
            "startRecord": "1",
            "recordSchema": "gzd",
        }
        if connection:
            params["x-connection"] = connection
        resp = client._get_raw_absolute_with_retry(endpoint, params=params, timeout=60)
        root = ET.fromstring(
            resp.content
        )  # bytes: the parser reads the declared encoding
        raise_on_diagnostic(root, context=f"{context} after {last}")

        if total is None:
            total = number_of_records(root)
        page = [e for e in root.iter() if local_name(e.tag) == "record"]
        identifiers = [i for i in map(record_identifier, page) if i]
        if len(identifiers) != len(page):
            raise RuntimeError(f"SRU error ({context}): a record has no identifier")
        fetched += len(page)
        for record in parse(root):
            if limit is not None and yielded >= limit:
                return
            yield record
            yielded += 1

        if len(page) < page_size or (limit is not None and yielded >= limit):
            break
        last = identifiers[-1]

    if limit is None and fetched != total:
        raise RuntimeError(
            f"SRU error ({context}): the pages hold {fetched} records, the service "
            f"reports {total}"
        )


def search_publications(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
    """Every record of a query as a list; see ``iter_publications``."""
    return list(iter_publications(*args, **kwargs))


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

        identifier = record_identifier(record_elem)
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
        record["modified"] = find_own_text(record_elem, "modified")
        for field_name in extra_fields:
            record[field_name] = find_own_text(record_elem, field_name)

        records.append(record)

    return records


def fetch_publication_xml(
    client: BaseClient,
    kind: str,
    id_pattern: re.Pattern[str],
    identifier: str,
    group: str | None = None,
) -> str | None:
    """The XML of a publication (``stb``, ``stcrt``, ``kst``) from the repository.

    The repository files a publication under a group: the year for the Staatsblad and the
    Staatscourant (the default), the dossier for a Kamerstuk (``37020`` or ``37020-X``).

    ``None`` when the identifier is malformed or the repository has no XML for it (404); any
    other failure raises, after the retries of ``BaseClient``.
    """
    if not id_pattern.search(identifier) or not _IDENTIFIER_RE.fullmatch(identifier):
        logger.warning("Cannot parse %s identifier: %s", kind, identifier)
        return None
    group = group or identifier.split("-")[1]
    url = (
        f"{client.base_url.rstrip('/')}/frbr/officielepublicaties/{kind}/{group}/"
        f"{identifier}/1/xml/{identifier}.xml"
    )
    try:
        return response_text(client._get_raw_absolute_with_retry(url, timeout=60))
    except requests.HTTPError as exc:
        if exc.response is not None and exc.response.status_code == 404:
            logger.debug("%s XML not found at %s (404)", kind, url)
            return None
        raise

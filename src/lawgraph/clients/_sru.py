"""The SRU of KOOP and of the BWB: the parameters of a search, its pages, its records."""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET
from collections.abc import Callable, Iterator
from typing import Any

from lawgraph.clients.base import PAGE_TIMEOUT, BaseClient, UnexpectedAnswer
from lawgraph.core.logging import get_logger
from lawgraph.core.xml import find_own_text, first_named, iter_named, local_name

logger = get_logger(__name__)

_IDENTIFIER_RE = re.compile(r"[\w.-]+")

SRU_PAGE_SIZE = 100


def sru_params(
    query: str,
    *,
    size: int,
    start: int | None = None,
    schema: str | None = None,
    connection: str | None = None,
) -> dict[str, str]:
    """The parameters of a ``searchRetrieve`` of *size* records from *start*; *connection*
    picks the collection (``x-connection``: ``BWB``, ``ob``; none for the repository's
    default)."""
    params = {"operation": "searchRetrieve", "version": "1.2", "query": query}
    params["maximumRecords"] = str(size)
    if start is not None:
        params["startRecord"] = str(start)
    if schema:
        params["recordSchema"] = schema
    if connection:
        params["x-connection"] = connection
    return params


def records(root: ET.Element) -> list[ET.Element]:
    """The ``<record>`` elements of a result page."""
    return list(iter_named(root, "record"))


def parse_response(content: bytes, *, context: str) -> ET.Element:
    """The root of an SRU result page; raises when *content* is anything else.

    A maintenance page sent with HTTP 200 can be well-formed XML, and an unsupported index
    or a bad query answers a ``<diagnostic>``: both would look like a search with no results.
    *content* is bytes: the parser reads the encoding the document declares.
    """
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise UnexpectedAnswer(f"not an SRU response ({context}): {exc}") from exc
    diagnostic = first_named(root, "diagnostic")
    if diagnostic is not None:
        message = find_own_text(diagnostic, "message") or "unknown SRU error"
        raise UnexpectedAnswer(f"SRU error ({context}): {message}")
    # After the diagnostics: BWB answers an error as a bare <diagnostics>.
    if local_name(root.tag) != "searchRetrieveResponse":
        raise UnexpectedAnswer(
            f"not an SRU response ({context}): the page is a <{local_name(root.tag)}>"
        )
    return root


def number_of_records(root: ET.Element) -> int:
    """The total the service reports for the query (``numberOfRecords``)."""
    return int(find_own_text(root, "numberOfRecords") or "0")


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


def record_dicts(
    root: ET.Element,
    fields: dict[str, str],
    **derived: Callable[[ET.Element], Any],
) -> list[dict[str, Any]]:
    """``{identifier, **fields, **derived}`` of every record of a result page: the
    single-valued *fields* by local element name, and each of *derived* computed from the
    record."""
    return [
        {
            "identifier": record_identifier(record),
            **parse_record_fields(record, fields),
            **{name: compute(record) for name, compute in derived.items()},
        }
        for record in records(root)
    ]


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
        params = sru_params(
            f"{query}{after} sortBy dt.identifier/sort.ascending",
            size=page_size,
            start=1,
            schema="gzd",
            connection=connection,
        )
        resp = client.get(endpoint, params=params, timeout=PAGE_TIMEOUT)
        root = parse_response(resp.content, context=f"{context} after {last}")

        if total is None:
            total = number_of_records(root)
        page = records(root)
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


def fetch_publication_xml(
    client: BaseClient,
    kind: str,
    id_pattern: re.Pattern[str],
    identifier: str,
    group: str | None = None,
) -> str:
    """The XML of a publication (``stb``, ``stcrt``, ``kst``) from the repository.

    The repository files a publication under a group: the year for the Staatsblad and the
    Staatscourant (the default), the dossier for a Kamerstuk (``37020`` or ``37020-X``).

    A failed request raises (``requests.HTTPError``, 404 when the repository has no XML),
    after the retries of ``BaseClient``; so does a malformed identifier, which is not asked
    for, and a page that is not XML (``UnexpectedAnswer``).
    """
    if not id_pattern.search(identifier) or not _IDENTIFIER_RE.fullmatch(identifier):
        raise UnexpectedAnswer(f"not a {kind} identifier: {identifier!r}")
    group = group or identifier.split("-")[1]
    url = (
        f"{client.base_url.rstrip('/')}/frbr/officielepublicaties/{kind}/{group}/"
        f"{identifier}/1/xml/{identifier}.xml"
    )
    return client.get_xml(url, timeout=PAGE_TIMEOUT)

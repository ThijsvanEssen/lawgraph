from __future__ import annotations

import re
import time
import xml.etree.ElementTree as ET
from enum import StrEnum
from typing import Any, TypedDict, Unpack

import requests

from lawgraph.clients.pacing import PacedSession, retry_after_seconds
from lawgraph.core.logging import get_logger
from lawgraph.core.xml import local_name

logger = get_logger(__name__)

RETRY_STATUSES = (429, 502, 503, 504)


class Unexpected(StrEnum):
    """What an answer was instead of what was asked for, in fixed words: the cause the run
    log and the alert give, without the URL or the record."""

    EMPTY_XML = "lege XML"
    NOT_XML = "geen XML"
    HTML_PAGE = "HTML-pagina"
    NOT_SRU = "geen SRU-antwoord"
    SRU_ERROR = "SRU-fout"
    TOO_MANY = "te veel resultaten"
    BAD_ID = "ongeldig id"
    NOT_PDF = "geen PDF"
    NOT_DOCX = "geen DOCX"


class UnexpectedAnswer(RuntimeError):
    """The source answered, but not with what was asked for: an SRU diagnostic, a
    maintenance page with HTTP 200, a document that is not XML; or it named a document by an
    identifier that cannot be asked for. *reason* is the cause in fixed words, *detail* the
    rest for the log (the URL, the parser's message)."""

    def __init__(self, reason: Unexpected, detail: str = "") -> None:
        super().__init__(f"{reason}: {detail}" if detail else str(reason))
        self.reason = reason


_XML_ENCODING = re.compile(rb"""<\?xml[^>]*encoding=["']([A-Za-z0-9._-]+)""")


def response_text(resp: requests.Response) -> str:
    """The body as text, decoded the way the document says and not the way requests guesses.

    For ``text/xml`` and ``text/html`` without a charset in the header, requests falls back
    to ISO-8859-1: a server that stops sending the charset would silently turn every stored
    text into mojibake. The header wins when it names a charset; else the XML declaration;
    else UTF-8, which is what XML without a declaration is.
    """
    if "charset" in resp.headers.get("Content-Type", "").lower():
        text: str = resp.text
        return text
    content: bytes = resp.content
    declared = _XML_ENCODING.match(content[:200].lstrip(b"\xef\xbb\xbf"))
    encoding = declared.group(1).decode("ascii") if declared else "utf-8"
    try:
        return content.decode(encoding, errors="replace")
    except LookupError:
        return content.decode("utf-8", errors="replace")


def xml_text(resp: requests.Response) -> str:
    """The body as text (``response_text``), when it is an XML document.

    An error or maintenance page the server answers with HTTP 200 is not one: stored, it
    would stand for the document until it changes at the source.
    """
    text = response_text(resp)
    if not text.strip("\ufeff \t\r\n"):
        raise UnexpectedAnswer(Unexpected.EMPTY_XML, resp.url)
    try:
        root = ET.fromstring(text.lstrip("\ufeff"))
    except ET.ParseError as exc:
        raise UnexpectedAnswer(Unexpected.NOT_XML, f"{exc}: {resp.url}") from exc
    if local_name(root.tag) == "html":
        raise UnexpectedAnswer(Unexpected.HTML_PAGE, resp.url)
    return text


# How long a request may take: an answer of an API; a page (a web page, a page of SRU results,
# a document of a repository); and what a source computes long (a BWB type listing, a SPARQL
# query, a DOCX conversion).
REQUEST_TIMEOUT = 30
PAGE_TIMEOUT = 60
QUERY_TIMEOUT = 120
# Attempts of a request before its failure is raised, and the base of the backoff between them.
ATTEMPTS = 5
BACKOFF = 2.0


class GetOptions(TypedDict, total=False):
    """The options of ``BaseClient.get`` besides the URL."""

    params: dict[str, Any] | None
    timeout: float
    headers: dict[str, str] | None
    stream: bool


class BaseClient:
    """HTTP client base: GET with retry against a full URL or a path under ``base_url``."""

    def __init__(
        self,
        *,
        base_url: str,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.session: requests.Session = session or PacedSession()

    def _build_url(self, path: str) -> str:
        """Join base_url (which has a trailing slash) with path (leading slash stripped)."""
        return self.base_url + path.lstrip("/")

    def get(
        self,
        url_or_path: str,
        *,
        params: dict[str, Any] | None = None,
        timeout: float = REQUEST_TIMEOUT,
        headers: dict[str, str] | None = None,
        stream: bool = False,
    ) -> requests.Response:
        """GET with exponential backoff on 429, 502, 503, 504 and connection errors; a
        ``Retry-After`` of the server is followed when it is longer than the backoff.

        Only HTTP 200 is an answer: any other status raises ``requests.HTTPError``. With
        *stream* the body is not downloaded; the caller reads it in chunks and closes the
        response.
        """
        url = (
            url_or_path
            if url_or_path.startswith(("http://", "https://"))
            else self._build_url(url_or_path)
        )
        for attempt in range(ATTEMPTS):
            try:
                return self._get_once(
                    url, params=params, timeout=timeout, headers=headers, stream=stream
                )
            except requests.exceptions.HTTPError as exc:
                if (
                    exc.response is None
                    or exc.response.status_code not in RETRY_STATUSES
                    or attempt + 1 == ATTEMPTS
                ):
                    raise
                wait = max(
                    BACKOFF**attempt,
                    retry_after_seconds(exc.response) or 0.0,
                )
                # Not a warning per request: the pacer reports a throttling host once
                # a minute, and the last failure is raised to the caller.
                logger.debug(
                    "HTTP %d from %s (attempt %d/%d), retrying in %.1fs",
                    exc.response.status_code,
                    url,
                    attempt + 1,
                    ATTEMPTS,
                    wait,
                )
            except (
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
            ) as exc:
                if attempt + 1 == ATTEMPTS:
                    raise
                wait = BACKOFF**attempt
                logger.debug(
                    "Connection error on %s (attempt %d/%d), retrying in %.1fs: %s",
                    url,
                    attempt + 1,
                    ATTEMPTS,
                    wait,
                    exc,
                )
            time.sleep(wait)
        raise AssertionError("unreachable: the last attempt returns or raises")

    def get_text(self, url_or_path: str, **options: Unpack[GetOptions]) -> str:
        """The body of ``get`` as text (``response_text``)."""
        return response_text(self.get(url_or_path, **options))

    def get_xml(self, url_or_path: str, **options: Unpack[GetOptions]) -> str:
        """The body of ``get`` as text, when it is an XML document (``xml_text``)."""
        return xml_text(self.get(url_or_path, **options))

    def get_json(self, url_or_path: str, **options: Unpack[GetOptions]) -> Any:
        """The body of ``get`` as JSON."""
        return self.get(url_or_path, **options).json()

    def _get_once(
        self,
        url: str,
        *,
        params: dict[str, Any] | None,
        timeout: float,
        headers: dict[str, str] | None,
        stream: bool,
    ) -> requests.Response:
        logger.debug("HTTP GET url=%s params=%r", url, params)
        resp = self.session.get(
            url, params=params, timeout=timeout, stream=stream, headers=headers
        )
        logger.debug(
            "HTTP response status=%s reason=%s",
            resp.status_code,
            resp.reason,
        )
        resp.raise_for_status()
        if resp.status_code != 200:
            # 202 Accepted, 204, 206, 300: no error for requests, and not the document
            # either. Stored as one it would never be fetched again.
            raise requests.HTTPError(
                f"{resp.status_code} is not the document: {url}", response=resp
            )
        return resp

from __future__ import annotations

import re
import time
from collections.abc import Iterator
from typing import Any

import requests

from lawgraph.clients.pacing import PacedSession, retry_after_seconds
from lawgraph.core.logging import get_logger
from lawgraph.core.values import next_page_link

logger = get_logger(__name__)

RETRY_STATUSES = (429, 502, 503, 504)


_XML_ENCODING = re.compile(rb"""<\?xml[^>]*encoding=["']([A-Za-z0-9._-]+)""")


def response_text(resp: requests.Response) -> str:
    """The body as text, decoded the way the document says and not the way requests guesses.

    For ``text/xml`` and ``text/html`` without a charset in the header, requests falls back
    to ISO-8859-1: a server that stops sending the charset would silently turn every stored
    text into mojibake. The header wins when it names a charset; else the XML declaration;
    else UTF-8, which is what XML without a declaration is.
    """
    if "charset" in resp.headers.get("Content-Type", "").lower():
        return resp.text
    declared = _XML_ENCODING.match(resp.content[:200].lstrip(b"\xef\xbb\xbf"))
    encoding = declared.group(1).decode("ascii") if declared else "utf-8"
    try:
        return resp.content.decode(encoding, errors="replace")
    except LookupError:
        return resp.content.decode("utf-8", errors="replace")


class BaseClient:
    """HTTP client base: URL joining, logged GET helpers with retry, OData paging."""

    def __init__(
        self,
        *,
        base_url: str,
        session: requests.Session | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.session: requests.Session = session or PacedSession()

        logger.debug(
            "Initialized %s with base_url=%s",
            self.__class__.__name__,
            self.base_url,
        )

    def _build_url(self, path: str) -> str:
        """Join base_url (which has a trailing slash) with path (leading slash stripped)."""
        return self.base_url + path.lstrip("/")

    def _get_raw_absolute(
        self,
        url: str,
        *,
        params: dict | None = None,
        timeout: float = 30,
        stream: bool = False,
        headers: dict[str, str] | None = None,
    ) -> requests.Response:
        """One HTTP GET against a full URL; ``_get_raw_absolute_with_retry`` is what clients call.

        With ``stream`` the body is not downloaded; the caller reads it in chunks and
        closes the response.
        """
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

    def _get_raw_with_retry(
        self,
        path: str,
        *,
        params: dict | None = None,
        timeout: float = 30,
        retries: int = 5,
        backoff_factor: float = 2.0,
    ) -> requests.Response:
        """GET with exponential backoff on 429, 502, 503, 504 and connection errors."""
        url = (
            path
            if path.startswith("http://") or path.startswith("https://")
            else self._build_url(path)
        )
        return self._get_raw_absolute_with_retry(
            url,
            params=params,
            timeout=timeout,
            retries=retries,
            backoff_factor=backoff_factor,
        )

    def _get_raw_absolute_with_retry(
        self,
        url: str,
        *,
        params: dict | None = None,
        timeout: float = 30,
        retries: int = 5,
        backoff_factor: float = 2.0,
        stream: bool = False,
        headers: dict[str, str] | None = None,
    ) -> requests.Response:
        """GET a full URL with exponential backoff on 429, 502, 503, 504 and connection errors.

        A ``Retry-After`` of the server is followed when it is longer than the backoff.
        """
        last_exc: Exception = RuntimeError("unreachable")
        for attempt in range(retries):
            try:
                resp = self._get_raw_absolute(
                    url,
                    params=params,
                    timeout=timeout,
                    stream=stream,
                    headers=headers,
                )
                # _get_raw_absolute already calls raise_for_status, but 429/503 need retry
                return resp
            except requests.exceptions.HTTPError as exc:
                if (
                    exc.response is not None
                    and exc.response.status_code in RETRY_STATUSES
                ):
                    last_exc = exc
                    wait = max(
                        backoff_factor**attempt,
                        retry_after_seconds(exc.response) or 0.0,
                    )
                    # Not a warning per request: the pacer reports a throttling host once
                    # a minute, and the last failure is raised to the caller.
                    logger.debug(
                        "HTTP %d from %s (attempt %d/%d), retrying in %.1fs",
                        exc.response.status_code,
                        url,
                        attempt + 1,
                        retries,
                        wait,
                    )
                    time.sleep(wait)
                    continue
                raise  # non-retryable HTTP error
            except (
                requests.exceptions.Timeout,
                requests.exceptions.ConnectionError,
            ) as exc:
                last_exc = exc
                wait = backoff_factor**attempt
                logger.debug(
                    "Connection error on %s (attempt %d/%d), retrying in %.1fs: %s",
                    url,
                    attempt + 1,
                    retries,
                    wait,
                    exc,
                )
                time.sleep(wait)
        raise last_exc

    def _get_json(
        self,
        path: str,
        *,
        params: dict | None = None,
        timeout: float = 30,
    ) -> dict[str, Any] | list[Any]:
        """Get JSON from the endpoint (with retry) and log item counts when present."""
        resp = self._get_raw_with_retry(path, params=params, timeout=timeout)
        data = resp.json()
        if isinstance(data, dict) and "value" in data:
            logger.debug("JSON payload: %d items in 'value'", len(data["value"]))
        return data

    def _get_text(
        self,
        path: str,
        *,
        params: dict | None = None,
        timeout: float = 30,
    ) -> str:
        """Retrieve the text of the requested resource (with retry)."""
        resp = self._get_raw_with_retry(path, params=params, timeout=timeout)
        return response_text(resp)

    def _paged_get(
        self,
        path: str,
        *,
        params: dict | None = None,
        timeout: float = 30,
        result_key: str = "value",
        next_link_key: str | None = "@odata.nextLink",
    ) -> Iterator[dict[str, Any]]:
        """
        Generic iterator for JSON endpoints that expose paged responses.

        Defaults follow the Microsoft OData style exposed by the TK API.
        """

        def _yield_entries(data: Any) -> Iterator[dict[str, Any]]:
            if isinstance(data, dict):
                entries = data.get(result_key)
                if isinstance(entries, list):
                    for entry in entries:
                        if isinstance(entry, dict):
                            yield entry
                else:
                    logger.warning(
                        "Paged response missing expected key %r; keys present: %s",
                        result_key,
                        list(data.keys()),
                    )
            elif isinstance(data, list):
                for entry in data:
                    if isinstance(entry, dict):
                        yield entry

        first_page = self._get_json(path, params=params, timeout=timeout)
        yield from _yield_entries(first_page)

        next_link = next_page_link(first_page, next_link_key)
        while next_link:
            logger.debug("Following pagination url=%s", next_link)
            resp = self._get_raw_absolute_with_retry(next_link, timeout=timeout)
            page_data = resp.json()
            yield from _yield_entries(page_data)
            next_link = next_page_link(page_data, next_link_key)

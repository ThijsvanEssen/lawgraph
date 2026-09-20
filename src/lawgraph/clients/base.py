from __future__ import annotations

import time
from collections.abc import Iterator
from typing import Any

import requests

from lawgraph.clients.pacing import PacedSession, retry_after_seconds
from lawgraph.core.logging import get_logger
from lawgraph.core.values import next_page_link

logger = get_logger(__name__)

RETRY_STATUSES = (429, 502, 503, 504)


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

    def _get_raw(
        self,
        path: str,
        *,
        params: dict | None = None,
        timeout: int = 30,
    ) -> requests.Response:
        """Perform an HTTP GET while logging the outgoing request and status."""
        url = self._build_url(path)
        return self._get_raw_absolute(url, params=params, timeout=timeout)

    def _get_raw_absolute(
        self,
        url: str,
        *,
        params: dict | None = None,
        timeout: int = 30,
        stream: bool = False,
    ) -> requests.Response:
        """Perform an HTTP GET against a full URL while logging request and status.

        With ``stream`` the body is not downloaded; the caller reads it in chunks and
        closes the response.
        """
        logger.debug("HTTP GET url=%s params=%r", url, params)
        resp = self.session.get(url, params=params, timeout=timeout, stream=stream)
        logger.debug(
            "HTTP response status=%s reason=%s",
            resp.status_code,
            resp.reason,
        )
        resp.raise_for_status()
        return resp

    def _get_raw_with_retry(
        self,
        path: str,
        *,
        params: dict | None = None,
        timeout: int = 30,
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
        timeout: int = 30,
        retries: int = 5,
        backoff_factor: float = 2.0,
        stream: bool = False,
    ) -> requests.Response:
        """GET a full URL with exponential backoff on 429, 502, 503, 504 and connection errors.

        A ``Retry-After`` of the server is followed when it is longer than the backoff.
        """
        last_exc: Exception = RuntimeError("unreachable")
        for attempt in range(retries):
            try:
                resp = self._get_raw_absolute(
                    url, params=params, timeout=timeout, stream=stream
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
                    logger.warning(
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
                logger.warning(
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
        timeout: int = 30,
    ) -> dict[str, Any] | list[Any]:
        """Get JSON from the endpoint and log item counts when present."""
        resp = self._get_raw(path, params=params, timeout=timeout)
        data = resp.json()
        if isinstance(data, dict) and "value" in data:
            logger.debug("JSON payload: %d items in 'value'", len(data["value"]))
        return data

    def _get_text(
        self,
        path: str,
        *,
        params: dict | None = None,
        timeout: int = 30,
    ) -> str:
        """Retrieve raw text payload for the requested resource."""
        resp = self._get_raw(path, params=params, timeout=timeout)
        return resp.text

    def _paged_get(
        self,
        path: str,
        *,
        params: dict | None = None,
        timeout: int = 30,
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

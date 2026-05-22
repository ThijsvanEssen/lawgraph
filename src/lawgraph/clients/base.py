from __future__ import annotations

import os
import time
from collections.abc import Iterator
from typing import Any

import requests

from lawgraph.core.logging import get_logger

logger = get_logger(__name__)


class BaseClient:
    """
    Basisclient voor HTTP-API's.

    - Leest base_url uit env (met fallback)
    - Normaliseert trailing slash
    - Biedt get_json / get_text / get_raw helpers met logging
    - Ondersteunt een generieke `_paged_get` voor op OData gebaseerde paginering
    """

    def __init__(
        self,
        *,
        env_var: str,
        default_base_url: str,
        session: requests.Session | None = None,
    ) -> None:
        """Load env vars and configure the HTTP session with a normalized base URL."""
        base = os.getenv(env_var, default_base_url)
        # force trailing slash
        self.base_url = base.rstrip("/") + "/"
        self.session: requests.Session = session or requests.Session()

        logger.debug(
            "Initialized %s with base_url=%s (env_var=%s)",
            self.__class__.__name__,
            self.base_url,
            env_var,
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
    ) -> requests.Response:
        """Perform an HTTP GET against a full URL while logging request and status."""
        logger.debug("HTTP GET url=%s params=%r", url, params)
        resp = self.session.get(url, params=params, timeout=timeout)
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
        retries: int = 3,
        backoff_factor: float = 2.0,
    ) -> requests.Response:
        """GET with exponential backoff on 429, 503, and connection errors."""
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
        retries: int = 3,
        backoff_factor: float = 2.0,
    ) -> requests.Response:
        """GET a full URL with exponential backoff on 429, 503, and connection errors."""
        last_exc: Exception = RuntimeError("unreachable")
        for attempt in range(retries):
            try:
                resp = self._get_raw_absolute(url, params=params, timeout=timeout)
                # _get_raw_absolute already calls raise_for_status, but 429/503 need retry
                return resp
            except requests.exceptions.HTTPError as exc:
                if exc.response is not None and exc.response.status_code in (429, 503):
                    last_exc = exc
                    wait = backoff_factor**attempt
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

        next_link = self._extract_next_link(first_page, next_link_key)
        while next_link:
            logger.debug("Following pagination url=%s", next_link)
            resp = self._get_raw_absolute_with_retry(next_link, timeout=timeout)
            page_data = resp.json()
            yield from _yield_entries(page_data)
            next_link = self._extract_next_link(page_data, next_link_key)

    @staticmethod
    def _extract_next_link(data: Any, key: str | None) -> str | None:
        """Read the pagination next-link key when present on the page payload."""
        if key is None or not isinstance(data, dict):
            return None
        candidate = data.get(key)
        if isinstance(candidate, str):
            stripped = candidate.strip()
            if stripped:
                return stripped
        return None

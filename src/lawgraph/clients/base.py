# src/lawgraph/clients/base.py
from __future__ import annotations

# Structural changes:
# - Documented all helpers and added a paginated getter shared across clients.
# - Ensured load_dotenv runs once while keeping consistent HTTP debug logging.

import os
from typing import Any, Iterator

import requests
from dotenv import load_dotenv

from lawgraph.logging import get_logger


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
        load_dotenv()

        base = os.getenv(env_var, default_base_url)
        # forceer trailing slash
        self.base_url = base.rstrip("/") + "/"
        self.session: requests.Session = session or requests.Session()

        logger.debug(
            "Initialized %s with base_url=%s (env_var=%s)",
            self.__class__.__name__,
            self.base_url,
            env_var,
        )

    def _build_url(self, path: str) -> str:
        """Construct a normalized URL that ensures a single trailing slash."""
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
        logger.debug("HTTP GET url=%s params=%r", url, params)
        resp = self.session.get(url, params=params, timeout=timeout)
        logger.debug(
            "HTTP response status=%s reason=%s",
            resp.status_code,
            resp.reason,
        )
        resp.raise_for_status()
        return resp

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
        first_page = self._get_json(path, params=params, timeout=timeout)
        yield from self._iter_page_entries(first_page, result_key)

        next_link = self._extract_next_link(first_page, next_link_key)
        while next_link:
            logger.debug("Following pagination url=%s", next_link)
            resp = self.session.get(next_link, timeout=timeout)
            logger.debug(
                "Paged HTTP response %s %s for url=%s",
                resp.status_code,
                resp.reason,
                next_link,
            )
            resp.raise_for_status()
            page_data = resp.json()
            yield from self._iter_page_entries(page_data, result_key)
            next_link = self._extract_next_link(page_data, next_link_key)

    @staticmethod
    def _iter_page_entries(data: Any, result_key: str) -> Iterator[dict[str, Any]]:
        """Extract the iterable of entries from a page, accepting dict or list payloads."""
        if isinstance(data, dict):
            entries = data.get(result_key)
            if isinstance(entries, list):
                for entry in entries:
                    if isinstance(entry, dict):
                        yield entry
            else:
                # Fallback to iterating over dict values when another key is used.
                for value in data.values():
                    if isinstance(value, list):
                        for element in value:
                            if isinstance(element, dict):
                                yield element
        elif isinstance(data, list):
            for entry in data:
                if isinstance(entry, dict):
                    yield entry

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

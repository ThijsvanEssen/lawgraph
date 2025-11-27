# src/lawgraph/clients/rechtspraak.py
from __future__ import annotations

import datetime as dt

from lawgraph.clients.base import BaseClient
from lawgraph.config.settings import RECHTSPRAAK_BASE_URL
from lawgraph.logging import get_logger

# Structural changes:
# - Base URL defers to lawgraph.config.settings and public methods now feature docstrings.


logger = get_logger(__name__)


class RechtspraakClient(BaseClient):
    """
    Client voor de RESTful webservice van de Rechtspraak.

    Docs:
      - https://www.rechtspraak.nl/Uitspraken/Paginas/Open-Data.aspx
    """

    def __init__(self, session=None) -> None:
        """Set up the Rechtspraak API client with optional session injection."""
        super().__init__(
            env_var="RECHTSPRAAK_BASE",
            default_base_url=RECHTSPRAAK_BASE_URL,
            session=session,
        )

    def search_ecli_index(
        self,
        modified_since: dt.datetime | None = None,
        extra_params: dict | None = None,
    ) -> str:
        """
        Retrieve the Rechtspraak index document URL (optionally filtering by modification date).
        """
        params: dict = extra_params.copy() if extra_params else {}

        if modified_since is not None:
            # exacte param-naam even afstemmen met de officiële doc
            params["modifiedsince"] = modified_since.replace(microsecond=0).isoformat()

        logger.info("Rechtspraak search index with params=%r", params)
        return self._get_text("uitspraken/zoeken", params=params)

    def fetch_ecli_content(self, ecli: str) -> str:
        """Retrieve the XML content for a single Rechtspraak ECLI."""
        logger.info("Fetching Rechtspraak content for %s", ecli)
        return self._get_text("uitspraken/content", params={"id": ecli})

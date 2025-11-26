# src/lawgraph/clients/eu.py
from __future__ import annotations

# Structural changes:
# - Default base URL now comes from lawgraph.config.settings and method is documented.

from lawgraph.clients.base import BaseClient
from lawgraph.config.settings import EU_BASE_URL
from lawgraph.logging import get_logger


logger = get_logger(__name__)


class EUClient(BaseClient):
    """
    Basic client voor EU-wetgeving (EUR-Lex / CELEX).
    """

    def __init__(self, session=None) -> None:
        super().__init__(
            env_var="EURLEX_BASE",
            default_base_url=EU_BASE_URL,
            session=session,
        )

    def fetch_celex_html(self, celex: str, lang: str = "NL") -> str:
        """Download the EUR-Lex HTML view for a CELEX number."""
        path = f"legal-content/{lang}/TXT/"
        params = {"uri": f"CELEX:{celex}"}
        logger.info("Fetching CELEX %s (%s)", celex, lang)
        return self._get_text(path, params=params)

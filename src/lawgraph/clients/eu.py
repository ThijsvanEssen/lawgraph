# src/lawgraph/clients/eu.py
from __future__ import annotations

from lawgraph.clients.base import BaseClient
from lawgraph.config.settings import EU_BASE_URL
from lawgraph.logging import get_logger

# Structural changes:
# - Default base URL now comes from lawgraph.config.settings and method is documented.


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
        """Download the EUR-Lex HTML via the Publications Office CELLAR content server.

        The main eur-lex.europa.eu website is behind AWS WAF and returns HTTP 202
        bot-challenge responses to automated clients.  The CELLAR server at
        publications.europa.eu accepts content-negotiation requests without
        bot-protection and redirects to the actual document (XHTML).
        """
        url = f"https://publications.europa.eu/resource/celex/{celex}"
        lang_lower = lang.lower()
        headers = {
            "Accept": "text/html, application/xhtml+xml",
            "Accept-Language": f"{lang_lower}, {lang_lower}-{lang.upper()};q=0.9",
        }
        logger.info("Fetching CELEX %s (%s) via CELLAR", celex, lang)
        resp = self.session.get(url, headers=headers, timeout=60, allow_redirects=True)
        resp.raise_for_status()
        return resp.text

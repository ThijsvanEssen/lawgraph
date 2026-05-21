"""Client for the Dutch Verdragenbank (treaty register).

Uses the SPARQL endpoint at linkeddata.overheid.nl to enumerate treaties
that the Netherlands is party to.

SPARQL endpoint: https://linkeddata.overheid.nl/front/portal/sparql
Verdragenbank: https://verdragenbank.overheid.nl/

Each treaty record provides:
  - title (Dutch and/or English)
  - date of signature / entry into force
  - parties
  - type (bilateral/multilateral)
  - status (in force / not in force)
  - treaty number (verdragsnummer)
"""

from __future__ import annotations

import time
from typing import Any

from lawgraph.clients.base import BaseClient
from lawgraph.config.settings import VERDRAGENBANK_SPARQL_ENDPOINT
from lawgraph.core.logging import get_logger

logger = get_logger(__name__)

_PAGE_SIZE = 200


_SPARQL_QUERY = """\
PREFIX skos: <http://www.w3.org/2004/02/skos/core#>
PREFIX dcterms: <http://purl.org/dc/terms/>
PREFIX owl: <http://www.w3.org/2002/07/owl#>
PREFIX vb: <https://linkeddata.overheid.nl/terms/verdragenbank/>

SELECT ?treaty ?title ?titleEn ?dateSigned ?dateInForce ?type ?status ?verdragsnummer
WHERE {{
  ?treaty a vb:Verdrag .
  OPTIONAL {{ ?treaty dcterms:title ?title . FILTER(LANG(?title) = 'nl') }}
  OPTIONAL {{ ?treaty dcterms:title ?titleEn . FILTER(LANG(?titleEn) = 'en') }}
  OPTIONAL {{ ?treaty vb:datumOndertekening ?dateSigned }}
  OPTIONAL {{ ?treaty vb:datumInwerkingtreding ?dateInForce }}
  OPTIONAL {{ ?treaty vb:soort ?type }}
  OPTIONAL {{ ?treaty vb:status ?status }}
  OPTIONAL {{ ?treaty vb:verdragsnummer ?verdragsnummer }}
}}
ORDER BY ?treaty
LIMIT {limit}
OFFSET {offset}
"""


class VerdragenbankClient(BaseClient):
    """Client for fetching treaties from the Dutch Verdragenbank via SPARQL."""

    def __init__(self, session=None) -> None:
        super().__init__(
            env_var="VERDRAGENBANK_SPARQL",
            default_base_url=VERDRAGENBANK_SPARQL_ENDPOINT,
            session=session,
        )
        self.session.headers.update({"Accept": "application/sparql-results+json"})

    def enumerate_treaties(self, max_records: int = 10000) -> list[dict[str, Any]]:
        """Enumerate all treaties from the Verdragenbank.

        Returns a list of treaty dicts with normalized field names.
        """
        results: list[dict[str, Any]] = []
        offset = 0

        while offset < max_records:
            query = _SPARQL_QUERY.format(limit=_PAGE_SIZE, offset=offset)
            try:
                resp = self.session.post(
                    self.base_url,
                    data={"query": query},
                    timeout=60,
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                logger.warning(
                    "Verdragenbank SPARQL query failed (offset=%d): %s", offset, exc
                )
                break

            bindings = data.get("results", {}).get("bindings", [])
            if not bindings:
                break

            for binding in bindings:

                def _val(key: str, _b: dict = binding) -> str | None:
                    entry = _b.get(key)
                    return entry["value"] if entry else None

                results.append(
                    {
                        "uri": _val("treaty"),
                        "title": _val("title") or _val("titleEn"),
                        "title_nl": _val("title"),
                        "title_en": _val("titleEn"),
                        "date_signed": _val("dateSigned"),
                        "date_in_force": _val("dateInForce"),
                        "treaty_type": _val("type"),
                        "status": _val("status"),
                        "verdragsnummer": _val("verdragsnummer"),
                    }
                )

            if len(bindings) < _PAGE_SIZE:
                break

            offset += _PAGE_SIZE
            time.sleep(0.3)

        logger.info("Verdragenbank: enumerated %d treaties.", len(results))
        return results

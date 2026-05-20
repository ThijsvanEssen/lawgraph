# src/lawgraph/clients/eu.py
from __future__ import annotations

from lawgraph.clients.base import BaseClient
from lawgraph.config.settings import EURLEX_BASE_URL, EURLEX_SPARQL_ENDPOINT
from lawgraph.core.logging import get_logger

logger = get_logger(__name__)

_CDM = "http://publications.europa.eu/ontology/cdm#"


class EUClient(BaseClient):
    """
    Basic client voor EU-wetgeving (EUR-Lex / CELEX).
    """

    def __init__(self, session=None) -> None:
        super().__init__(
            env_var="EURLEX_BASE",
            default_base_url=EURLEX_BASE_URL,
            session=session,
        )

    def enumerate_all_ids(
        self,
        *,
        cdm_types: tuple[str, ...] = ("regulation", "directive", "decision"),
        max_records: int = 200000,
    ) -> list[str]:
        """Enumerate CELEX IDs via the CELLAR SPARQL endpoint, one query per CDM type.

        Paginates with LIMIT/OFFSET until the page is smaller than the page size or
        ``max_records`` is reached. Returns all unique CELEX identifiers found.
        """
        all_ids: list[str] = []
        seen: set[str] = set()
        page_size = 500

        for cdm_type in cdm_types:
            logger.info("Enumerating EUR-Lex CELEX IDs for cdm_type=%s", cdm_type)
            offset = 0
            while offset < max_records:
                sparql = (
                    f"PREFIX cdm: <{_CDM}> "
                    "SELECT DISTINCT ?celex WHERE { "
                    f"?s a cdm:{cdm_type} ; "
                    "cdm:resource_legal_id_celex ?celex . "
                    "} "
                    f"ORDER BY ?celex LIMIT {page_size} OFFSET {offset}"
                )
                try:
                    resp = self.session.get(
                        EURLEX_SPARQL_ENDPOINT,
                        params={
                            "query": sparql,
                            "format": "application/sparql-results+json",
                        },
                        timeout=120,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                except Exception as exc:
                    logger.warning(
                        "SPARQL enumeration error (cdm_type=%s, offset=%d): %s",
                        cdm_type,
                        offset,
                        exc,
                    )
                    break

                bindings = data.get("results", {}).get("bindings", [])
                for binding in bindings:
                    celex = binding.get("celex", {}).get("value", "")
                    if celex and celex not in seen:
                        seen.add(celex)
                        all_ids.append(celex)

                if len(bindings) < page_size:
                    break
                offset += page_size

            logger.info(
                "Enumerated %d unique CELEX IDs so far (cdm_type=%s done).",
                len(all_ids),
                cdm_type,
            )

        logger.info("EUR-Lex enumeration complete: %d unique IDs total.", len(all_ids))
        return all_ids

    def enumerate_nim_ids(
        self,
        *,
        country_code: str = "NLD",
        max_records: int = 200000,
    ) -> list[str]:
        """Enumerate CELEX IDs of EU acts that have national implementation measures
        for the given country (default ``"NLD"`` = Netherlands).

        Paginates with LIMIT/OFFSET using the same approach as ``enumerate_all_ids()``.
        Returns all unique CELEX identifiers found.
        """
        all_ids: list[str] = []
        seen: set[str] = set()
        page_size = 500
        offset = 0

        logger.info(
            "Enumerating EUR-Lex CELEX IDs with NIM for country=%s", country_code
        )

        while offset < max_records:
            sparql = (
                f"PREFIX cdm: <{_CDM}> "
                "SELECT DISTINCT ?celex WHERE { "
                "?eu_act cdm:resource_legal_id_celex ?celex . "
                "?nim cdm:national_implementation_measure_implements ?eu_act ; "
                "cdm:national_implementation_measure_country "
                f"<http://publications.europa.eu/resource/authority/country/{country_code}> . "
                "} "
                f"ORDER BY ?celex LIMIT {page_size} OFFSET {offset}"
            )
            try:
                resp = self.session.get(
                    EURLEX_SPARQL_ENDPOINT,
                    params={
                        "query": sparql,
                        "format": "application/sparql-results+json",
                    },
                    timeout=120,
                )
                resp.raise_for_status()
                data = resp.json()
            except Exception as exc:
                logger.warning(
                    "SPARQL NIM enumeration error (country=%s, offset=%d): %s",
                    country_code,
                    offset,
                    exc,
                )
                break

            bindings = data.get("results", {}).get("bindings", [])
            for binding in bindings:
                celex = binding.get("celex", {}).get("value", "")
                if celex and celex not in seen:
                    seen.add(celex)
                    all_ids.append(celex)

            if len(bindings) < page_size:
                break
            offset += page_size

        logger.info(
            "EUR-Lex NIM enumeration complete: %d unique IDs (country=%s).",
            len(all_ids),
            country_code,
        )
        return all_ids

    def enumerate_cjeu_ids(
        self,
        *,
        celex_ids: list[str] | None = None,
        country_code: str = "NLD",
        max_records: int = 200_000,
    ) -> list[str]:
        """Enumerate CELEX IDs for CJEU judgments.

        Two modes:
        - If ``celex_ids`` provided: find judgments that cite any of those instruments
          (batched in groups of 50).
        - Otherwise: find judgments related to the given country (default NLD).

        Returns a deduplicated list of CELEX IDs.
        """
        all_ids: list[str] = []
        seen: set[str] = set()
        page_size = 500

        if celex_ids:
            # Batch the input CELEX IDs in groups of 50
            batch_size = 50
            for batch_start in range(0, len(celex_ids), batch_size):
                batch = celex_ids[batch_start : batch_start + batch_size]
                celex_values = ", ".join(f'"{c}"' for c in batch)
                offset = 0
                while offset < max_records:
                    sparql = (
                        f"PREFIX cdm: <{_CDM}> "
                        "SELECT DISTINCT ?judgment_celex WHERE { "
                        "?j a cdm:judgment ; "
                        "cdm:resource_legal_id_celex ?judgment_celex ; "
                        "cdm:work_cites_work ?cited . "
                        "?cited cdm:resource_legal_id_celex ?cited_celex . "
                        f"FILTER(?cited_celex IN ({celex_values})) "
                        "} "
                        f"ORDER BY ?judgment_celex LIMIT {page_size} OFFSET {offset}"
                    )
                    try:
                        resp = self.session.get(
                            EURLEX_SPARQL_ENDPOINT,
                            params={
                                "query": sparql,
                                "format": "application/sparql-results+json",
                            },
                            timeout=120,
                        )
                        resp.raise_for_status()
                        data = resp.json()
                    except Exception as exc:
                        logger.warning(
                            "SPARQL CJEU enumeration error (batch=%d, offset=%d): %s",
                            batch_start,
                            offset,
                            exc,
                        )
                        break

                    bindings = data.get("results", {}).get("bindings", [])
                    for binding in bindings:
                        celex = binding.get("judgment_celex", {}).get("value", "")
                        if celex and celex not in seen:
                            seen.add(celex)
                            all_ids.append(celex)

                    if len(bindings) < page_size:
                        break
                    offset += page_size
        else:
            # Country-based query
            logger.info(
                "Enumerating CJEU judgment CELEX IDs for country=%s", country_code
            )
            offset = 0
            while offset < max_records:
                sparql = (
                    f"PREFIX cdm: <{_CDM}> "
                    "SELECT DISTINCT ?celex WHERE { "
                    "?j a cdm:judgment ; "
                    "cdm:resource_legal_id_celex ?celex ; "
                    "cdm:case_law_relates_to_country "
                    f"<http://publications.europa.eu/resource/authority/country/{country_code}> . "
                    "} "
                    f"ORDER BY ?celex LIMIT {page_size} OFFSET {offset}"
                )
                try:
                    resp = self.session.get(
                        EURLEX_SPARQL_ENDPOINT,
                        params={
                            "query": sparql,
                            "format": "application/sparql-results+json",
                        },
                        timeout=120,
                    )
                    resp.raise_for_status()
                    data = resp.json()
                except Exception as exc:
                    logger.warning(
                        "SPARQL CJEU country enumeration error (country=%s, offset=%d): %s",
                        country_code,
                        offset,
                        exc,
                    )
                    break

                bindings = data.get("results", {}).get("bindings", [])
                for binding in bindings:
                    celex = binding.get("celex", {}).get("value", "")
                    if celex and celex not in seen:
                        seen.add(celex)
                        all_ids.append(celex)

                if len(bindings) < page_size:
                    break
                offset += page_size

        logger.info("CJEU enumeration complete: %d unique judgment IDs.", len(all_ids))
        return all_ids

    def enumerate_com_ids(
        self,
        *,
        celex_ids: list[str],
        max_records: int = 200_000,
    ) -> list[str]:
        """Enumerate COM proposal CELEX IDs for the given instrument CELEX IDs.

        Batches the input in groups of 50 and tries two SPARQL predicates:
        ``cdm:based_on_regulation`` and ``cdm:act_based_on_proposal``.

        Returns a deduplicated list of COM CELEX IDs (typically starting with '5').
        """
        all_ids: list[str] = []
        seen: set[str] = set()
        page_size = 500
        batch_size = 50

        predicates = [
            "cdm:based_on_regulation",
            "cdm:act_based_on_proposal",
        ]

        for predicate in predicates:
            for batch_start in range(0, len(celex_ids), batch_size):
                batch = celex_ids[batch_start : batch_start + batch_size]
                celex_values = ", ".join(f'"{c}"' for c in batch)
                offset = 0
                while offset < max_records:
                    sparql = (
                        f"PREFIX cdm: <{_CDM}> "
                        "SELECT DISTINCT ?com_celex WHERE { "
                        "?act cdm:resource_legal_id_celex ?act_celex ; "
                        f"{predicate} ?proposal . "
                        "?proposal cdm:resource_legal_id_celex ?com_celex . "
                        f"FILTER(?act_celex IN ({celex_values})) "
                        "} "
                        f"ORDER BY ?com_celex LIMIT {page_size} OFFSET {offset}"
                    )
                    try:
                        resp = self.session.get(
                            EURLEX_SPARQL_ENDPOINT,
                            params={
                                "query": sparql,
                                "format": "application/sparql-results+json",
                            },
                            timeout=120,
                        )
                        resp.raise_for_status()
                        data = resp.json()
                    except Exception as exc:
                        logger.warning(
                            "SPARQL COM enumeration error (predicate=%s, batch=%d, offset=%d): %s",
                            predicate,
                            batch_start,
                            offset,
                            exc,
                        )
                        break

                    bindings = data.get("results", {}).get("bindings", [])
                    for binding in bindings:
                        celex = binding.get("com_celex", {}).get("value", "")
                        if celex and celex not in seen:
                            seen.add(celex)
                            all_ids.append(celex)

                    if len(bindings) < page_size:
                        break
                    offset += page_size

        logger.info(
            "COM proposal enumeration complete: %d unique COM IDs.", len(all_ids)
        )
        return all_ids

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

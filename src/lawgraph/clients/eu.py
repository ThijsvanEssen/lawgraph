# src/lawgraph/clients/eu.py
from __future__ import annotations

from collections.abc import Callable

from lawgraph.clients.base import BaseClient
from lawgraph.config.settings import EURLEX_BASE_URL, EURLEX_SPARQL_ENDPOINT
from lawgraph.core.logging import get_logger

logger = get_logger(__name__)

_CDM = "http://publications.europa.eu/ontology/cdm#"
_PAGE_SIZE = 500


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

    def _paginate_sparql(
        self,
        sparql_factory: Callable[[int], str],
        *,
        result_var: str,
        max_records: int,
        all_ids: list[str],
        seen: set[str],
        log_context: str = "",
    ) -> None:
        """Run a SPARQL query with LIMIT/OFFSET pagination, appending results to all_ids."""
        offset = 0
        ctx = f" ({log_context})" if log_context else ""
        while offset < max_records:
            try:
                resp = self._get_raw_absolute_with_retry(
                    EURLEX_SPARQL_ENDPOINT,
                    params={
                        "query": sparql_factory(offset),
                        "format": "application/sparql-results+json",
                    },
                    timeout=120,
                )
                data = resp.json()
            except Exception as exc:
                logger.warning(
                    "SPARQL pagination error%s offset=%d: %s", ctx, offset, exc
                )
                break

            bindings = data.get("results", {}).get("bindings", [])
            for binding in bindings:
                celex = binding.get(result_var, {}).get("value", "")
                if celex and celex not in seen:
                    seen.add(celex)
                    all_ids.append(celex)

            if len(bindings) < _PAGE_SIZE:
                break
            offset += _PAGE_SIZE

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

        for cdm_type in cdm_types:
            logger.info("Enumerating EUR-Lex CELEX IDs for cdm_type=%s", cdm_type)
            self._paginate_sparql(
                lambda offset, t=cdm_type: (
                    f"PREFIX cdm: <{_CDM}> "
                    "SELECT DISTINCT ?celex WHERE { "
                    f"?s a cdm:{t} ; "
                    "cdm:resource_legal_id_celex ?celex . "
                    "} "
                    f"ORDER BY ?celex LIMIT {_PAGE_SIZE} OFFSET {offset}"
                ),
                result_var="celex",
                max_records=max_records,
                all_ids=all_ids,
                seen=seen,
                log_context=f"cdm_type={cdm_type}",
            )
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

        logger.info(
            "Enumerating EUR-Lex CELEX IDs with NIM for country=%s", country_code
        )
        self._paginate_sparql(
            lambda offset: (
                f"PREFIX cdm: <{_CDM}> "
                "SELECT DISTINCT ?celex WHERE { "
                "?eu_act cdm:resource_legal_id_celex ?celex . "
                "?nim cdm:national_implementation_measure_implements ?eu_act ; "
                "cdm:national_implementation_measure_country "
                f"<http://publications.europa.eu/resource/authority/country/{country_code}> . "
                "} "
                f"ORDER BY ?celex LIMIT {_PAGE_SIZE} OFFSET {offset}"
            ),
            result_var="celex",
            max_records=max_records,
            all_ids=all_ids,
            seen=seen,
            log_context=f"country={country_code}",
        )
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
        batch_size = 50

        if celex_ids:
            for batch_start in range(0, len(celex_ids), batch_size):
                batch = celex_ids[batch_start : batch_start + batch_size]
                celex_values = ", ".join(f'"{c}"' for c in batch)
                self._paginate_sparql(
                    lambda offset, cv=celex_values: (
                        f"PREFIX cdm: <{_CDM}> "
                        "SELECT DISTINCT ?judgment_celex WHERE { "
                        "?j a cdm:judgment ; "
                        "cdm:resource_legal_id_celex ?judgment_celex ; "
                        "cdm:work_cites_work ?cited . "
                        "?cited cdm:resource_legal_id_celex ?cited_celex . "
                        f"FILTER(?cited_celex IN ({cv})) "
                        "} "
                        f"ORDER BY ?judgment_celex LIMIT {_PAGE_SIZE} OFFSET {offset}"
                    ),
                    result_var="judgment_celex",
                    max_records=max_records,
                    all_ids=all_ids,
                    seen=seen,
                    log_context=f"batch={batch_start}",
                )
        else:
            logger.info(
                "Enumerating CJEU judgment CELEX IDs for country=%s", country_code
            )
            self._paginate_sparql(
                lambda offset: (
                    f"PREFIX cdm: <{_CDM}> "
                    "SELECT DISTINCT ?celex WHERE { "
                    "?j a cdm:judgment ; "
                    "cdm:resource_legal_id_celex ?celex ; "
                    "cdm:case_law_relates_to_country "
                    f"<http://publications.europa.eu/resource/authority/country/{country_code}> . "
                    "} "
                    f"ORDER BY ?celex LIMIT {_PAGE_SIZE} OFFSET {offset}"
                ),
                result_var="celex",
                max_records=max_records,
                all_ids=all_ids,
                seen=seen,
                log_context=f"country={country_code}",
            )

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
        batch_size = 50

        predicates = [
            "cdm:based_on_regulation",
            "cdm:act_based_on_proposal",
        ]

        for predicate in predicates:
            for batch_start in range(0, len(celex_ids), batch_size):
                batch = celex_ids[batch_start : batch_start + batch_size]
                celex_values = ", ".join(f'"{c}"' for c in batch)
                self._paginate_sparql(
                    lambda offset, cv=celex_values, pred=predicate: (
                        f"PREFIX cdm: <{_CDM}> "
                        "SELECT DISTINCT ?com_celex WHERE { "
                        "?act cdm:resource_legal_id_celex ?act_celex ; "
                        f"{pred} ?proposal . "
                        "?proposal cdm:resource_legal_id_celex ?com_celex . "
                        f"FILTER(?act_celex IN ({cv})) "
                        "} "
                        f"ORDER BY ?com_celex LIMIT {_PAGE_SIZE} OFFSET {offset}"
                    ),
                    result_var="com_celex",
                    max_records=max_records,
                    all_ids=all_ids,
                    seen=seen,
                    log_context=f"predicate={predicate}, batch={batch_start}",
                )

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
        # Cannot use _get_raw_absolute_with_retry here: it does not support custom
        # headers or allow_redirects, both of which are required for CELLAR content
        # negotiation and redirect following.
        resp = self.session.get(url, headers=headers, timeout=60, allow_redirects=True)
        resp.raise_for_status()
        return resp.text

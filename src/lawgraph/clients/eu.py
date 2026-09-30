# src/lawgraph/clients/eu.py
from __future__ import annotations

from collections.abc import Callable, Iterator
from functools import partial
from typing import Any

from lawgraph.clients.base import BaseClient, response_text
from lawgraph.config.settings import EURLEX_BASE_URL, EURLEX_SPARQL_ENDPOINT
from lawgraph.core.logging import get_logger

logger = get_logger(__name__)

_CDM = "http://publications.europa.eu/ontology/cdm#"
_CMR = "http://publications.europa.eu/ontology/cdm/cmr#"
_COUNTRY = "http://publications.europa.eu/resource/authority/country/"
_PAGE_SIZE = 500
# What a national implementing measure says, by the name of its SPARQL variable.
_MEASURE_FIELDS = ("journal", "number", "date", "type", "title")


class EUClient(BaseClient):
    """
    Basic client voor EU-wetgeving (EUR-Lex / CELEX).
    """

    def __init__(self, session=None) -> None:
        super().__init__(
            base_url=EURLEX_BASE_URL,
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
        """Run a SPARQL query with LIMIT/OFFSET pagination, appending results to all_ids.

        Raises ``RuntimeError`` when a page fails: the endpoint answers HTTP 500 from
        offset 10000 on, and a list cut off there must not pass for the whole result.
        """
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
                raise RuntimeError(
                    f"SPARQL pagination error{ctx} offset={offset}: {exc}"
                ) from exc

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
        cdm_types: tuple[str, ...] = ("directive",),
        max_records: int = 200000,
    ) -> list[str]:
        """Enumerate CELEX IDs via the CELLAR SPARQL endpoint, one query per CDM type.

        Paginates with LIMIT/OFFSET until the page is smaller than the page size or
        ``max_records`` is reached. Returns all unique CELEX identifiers found.

        Corrigenda and republications (``31983L0091R(03)``, an id with a bracket) are left
        out: CELLAR has no text page for them. The endpoint is incomplete for recent years
        (about 150 directives for 2010 but 1 for 2016) and stops at offset 10000, which is
        why only directives are listed by default; regulations and decisions are better
        fetched by the CELEX numbers that loaded records refer to (``--mode gaps``).
        """
        all_ids: list[str] = []
        seen: set[str] = set()

        for cdm_type in cdm_types:
            logger.info("Enumerating EUR-Lex CELEX IDs for cdm_type=%s", cdm_type)
            self._paginate_sparql(
                partial(_acts_of_type_sparql, cdm_type),
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
                "?nim cdm:measure_national_implementing_implements_resource_legal ?eu_act ; "
                "cdm:measure_national_implementing_implemented_by_country "
                f"<{_COUNTRY}{country_code}> . "
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

    def national_measures(
        self, *, country_code: str = "NLD", since: str | None = None
    ) -> Iterator[dict[str, Any]]:
        """The national implementing measures of a country in CELLAR, a page of measures
        per request, ordered by their document id: ``{id, modified, celex, journal, number,
        date, type, title}``, ``celex`` the EU acts the measure implements. *since*
        (``YYYY-MM-DD``) keeps the measures CELLAR changed on or after that day.

        Paged by key (the last document id), not by offset: the endpoint answers HTTP 500
        from offset 10000 on. A page that fails raises: a list cut off must not pass for
        the whole.
        """
        last = ""
        while True:
            resp = self._get_raw_absolute_with_retry(
                EURLEX_SPARQL_ENDPOINT,
                params={
                    "query": _measures_sparql(country_code, since, last),
                    "format": "application/sparql-results+json",
                },
                timeout=120,
            )
            bindings = resp.json().get("results", {}).get("bindings", [])
            measures = _measures(bindings)
            yield from measures
            if len(measures) < _PAGE_SIZE:
                return
            last = max(measure["id"] for measure in measures)

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
                    partial(_judgments_citing_sparql, celex_values),
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
                    partial(_proposals_of_sparql, predicate, celex_values),
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
        logger.debug("Fetching CELEX %s (%s) via CELLAR", celex, lang)
        # CELLAR negotiates the content on these headers and redirects to the document.
        resp = self._get_raw_absolute_with_retry(url, headers=headers, timeout=60)
        return response_text(resp)


# ── the SPARQL of one page; ``partial`` fixes all but the offset ─────────────


def _measures_sparql(country_code: str, since: str | None, after: str) -> str:
    """A page of measures (with every act each implements) whose id sorts after *after*."""
    window = (
        f'FILTER(?modified >= "{since}T00:00:00"^^<http://www.w3.org/2001/XMLSchema#dateTime>) '
        if since
        else ""
    )
    optional = " ".join(
        f"OPTIONAL {{ ?m cdm:{predicate} ?{name} }}"
        for name, predicate in (
            ("journal", "measure_national_implementing_name_official_journal"),
            ("number", "measure_national_implementing_number_official_journal"),
            ("date", "measure_national_implementing_date_official_journal"),
            ("type", "measure_national_implementing_type_act"),
            ("title", "work_title"),
        )
    )
    return (
        f"PREFIX cdm: <{_CDM}> PREFIX cmr: <{_CMR}> "
        "SELECT ?id ?modified ?celex ?journal ?number ?date ?type ?title WHERE { "
        "{ SELECT ?m ?id ?modified WHERE { "
        "?m cdm:measure_national_implementing_implemented_by_country "
        f"<{_COUNTRY}{country_code}> ; "
        "cdm:work_id_document ?id ; cmr:lastModificationDate ?modified . "
        f'{window}FILTER(STR(?id) > "{after}") '
        f"}} ORDER BY ?id LIMIT {_PAGE_SIZE} }} "
        "OPTIONAL { ?m cdm:measure_national_implementing_implements_resource_legal ?act . "
        "?act cdm:resource_legal_id_celex ?celex } "
        f"{optional} }} ORDER BY ?id"
    )


def _measures(bindings: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """One dict per measure from the rows of a page (a row per act and value)."""
    by_id: dict[str, dict[str, Any]] = {}
    for row in bindings:
        values = {name: cell.get("value") for name, cell in row.items()}
        measure = by_id.setdefault(
            values["id"],
            {"id": values["id"], "modified": values.get("modified"), "celex": []},
        )
        if values.get("celex") and values["celex"] not in measure["celex"]:
            measure["celex"].append(values["celex"])
        for name in _MEASURE_FIELDS:
            if values.get(name) and not measure.get(name):
                measure[name] = values[name].strip()
    return list(by_id.values())


def _acts_of_type_sparql(cdm_type: str, offset: int) -> str:
    return (
        f"PREFIX cdm: <{_CDM}> "
        "SELECT DISTINCT ?celex WHERE { "
        f"?s a cdm:{cdm_type} ; "
        "cdm:resource_legal_id_celex ?celex . "
        'FILTER(!CONTAINS(?celex, "(")) '
        "} "
        f"ORDER BY ?celex LIMIT {_PAGE_SIZE} OFFSET {offset}"
    )


def _judgments_citing_sparql(celex_values: str, offset: int) -> str:
    return (
        f"PREFIX cdm: <{_CDM}> "
        "SELECT DISTINCT ?judgment_celex WHERE { "
        "?j a cdm:judgment ; "
        "cdm:resource_legal_id_celex ?judgment_celex ; "
        "cdm:work_cites_work ?cited . "
        "?cited cdm:resource_legal_id_celex ?cited_celex . "
        f"FILTER(?cited_celex IN ({celex_values})) "
        "} "
        f"ORDER BY ?judgment_celex LIMIT {_PAGE_SIZE} OFFSET {offset}"
    )


def _proposals_of_sparql(predicate: str, celex_values: str, offset: int) -> str:
    return (
        f"PREFIX cdm: <{_CDM}> "
        "SELECT DISTINCT ?com_celex WHERE { "
        "?act cdm:resource_legal_id_celex ?act_celex ; "
        f"{predicate} ?proposal . "
        "?proposal cdm:resource_legal_id_celex ?com_celex . "
        f"FILTER(?act_celex IN ({celex_values})) "
        "} "
        f"ORDER BY ?com_celex LIMIT {_PAGE_SIZE} OFFSET {offset}"
    )

"""Client for EU law in CELLAR, the repository of the Publications Office: CELEX numbers
listed by SPARQL, and the text of an act by content negotiation."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from functools import partial
from typing import Any

import requests

from lawgraph.clients.base import PAGE_TIMEOUT, QUERY_TIMEOUT, BaseClient
from lawgraph.config.sources import CELLAR, CELLAR_SPARQL
from lawgraph.core.logging import get_logger
from lawgraph.core.time import is_later

logger = get_logger(__name__)

_CDM = "http://publications.europa.eu/ontology/cdm#"
_CMR = "http://publications.europa.eu/ontology/cdm/cmr#"
_XSD = "http://www.w3.org/2001/XMLSchema#"
_COUNTRY = "http://publications.europa.eu/resource/authority/country/"
_PAGE_SIZE = 500
# The end of a listing by offset, whatever the endpoint still has.
MAX_RECORDS = 200_000
# CELEX numbers asked for in one query.
CELEX_BATCH = 50
# CELEX numbers asked for their date in one query: the query goes in the URL, which the
# endpoint refuses (HTTP 414) at 500.
DATES_BATCH = 200
# What a national implementing measure says, by the name of its SPARQL variable.
_MEASURE_FIELDS = ("journal", "number", "date", "type", "title")


class EUClient(BaseClient):
    """Client for CELLAR: CELEX numbers by SPARQL, and the HTML of an act."""

    def __init__(self, session: requests.Session | None = None) -> None:
        super().__init__(base_url=CELLAR.base_url, session=session)

    def enumerate_all_ids(
        self, *, cdm_types: tuple[str, ...] = ("directive",)
    ) -> list[str]:
        """The CELEX numbers of the acts of each CDM type, each once, in the order found.

        Corrigenda and republications (``31983L0091R(03)``, an id with a bracket) are left
        out: CELLAR has no text page for them. The endpoint is incomplete for recent years
        (about 150 directives for 2010 but 1 for 2016) and stops at offset 10000, which is
        why only directives are listed by default; regulations and decisions are better
        fetched by the CELEX numbers that loaded records refer to (``--mode gaps``).
        """
        found: dict[str, None] = {}
        for cdm_type in cdm_types:
            logger.info("Enumerating EUR-Lex CELEX IDs for cdm_type=%s", cdm_type)
            found.update(
                dict.fromkeys(
                    self._paged(
                        partial(_acts_of_type_sparql, cdm_type),
                        "celex",
                        f"cdm_type={cdm_type}",
                    )
                )
            )
            logger.info(
                "Enumerated %d unique CELEX IDs so far (cdm_type=%s done).",
                len(found),
                cdm_type,
            )
        logger.info("EUR-Lex enumeration complete: %d unique IDs total.", len(found))
        return list(found)

    def enumerate_nim_ids(self, *, country_code: str = "NLD") -> list[str]:
        """The CELEX numbers of the EU acts that have national implementing measures of
        *country_code* (``NLD``), each once."""
        logger.info(
            "Enumerating EUR-Lex CELEX IDs with NIM for country=%s", country_code
        )
        found = list(
            dict.fromkeys(
                self._paged(
                    partial(_implemented_acts_sparql, country_code),
                    "celex",
                    f"country={country_code}",
                )
            )
        )
        logger.info(
            "EUR-Lex NIM enumeration complete: %d unique IDs (country=%s).",
            len(found),
            country_code,
        )
        return found

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
            measures = _measures(
                self._bindings(
                    _measures_sparql(country_code, since, last),
                    f"SPARQL page (country={country_code}) after {last!r}",
                )
            )
            yield from measures
            if len(measures) < _PAGE_SIZE:
                return
            last = max(measure["id"] for measure in measures)

    def enumerate_cjeu_ids(
        self,
        *,
        celex_ids: list[str] | None = None,
        country_code: str = "NLD",
    ) -> list[str]:
        """The CELEX numbers of CJEU judgments, each once: those that cite one of
        *celex_ids* (asked ``CELEX_BATCH`` at a time), or without them those related to
        *country_code*."""
        if celex_ids:
            found = dict.fromkeys(
                celex
                for start, batch in _batches(celex_ids)
                for celex in self._paged(
                    partial(_judgments_citing_sparql, batch),
                    "judgment_celex",
                    f"batch={start}",
                )
            )
        else:
            logger.info(
                "Enumerating CJEU judgment CELEX IDs for country=%s", country_code
            )
            found = dict.fromkeys(
                self._paged(
                    partial(_country_judgments_sparql, country_code),
                    "celex",
                    f"country={country_code}",
                )
            )
        logger.info("CJEU enumeration complete: %d unique judgment IDs.", len(found))
        return list(found)

    def enumerate_com_ids(self, *, celex_ids: list[str]) -> list[str]:
        """The CELEX numbers of the Commission proposals (typically starting with '5') the
        acts *celex_ids* are based on, each once, by two predicates:
        ``cdm:based_on_regulation`` and ``cdm:act_based_on_proposal``; asked
        ``CELEX_BATCH`` acts at a time."""
        found = list(
            dict.fromkeys(
                celex
                for predicate in (
                    "cdm:based_on_regulation",
                    "cdm:act_based_on_proposal",
                )
                for start, batch in _batches(celex_ids)
                for celex in self._paged(
                    partial(_proposals_of_sparql, predicate, batch),
                    "com_celex",
                    f"predicate={predicate}, batch={start}",
                )
            )
        )
        logger.info("COM proposal enumeration complete: %d unique COM IDs.", len(found))
        return found

    def last_modified(self, celex_ids: list[str]) -> dict[str, str]:
        """``{celex: moment}``: when CELLAR last changed each act of *celex_ids* it has
        (``cmr:lastModificationDate`` of the work, ``2024-12-31T20:10:26.804+01:00``), asked
        ``DATES_BATCH`` at a time. An act CELLAR does not know is left out; a page that
        fails raises."""
        dates: dict[str, str] = {}
        for start in range(0, len(celex_ids), DATES_BATCH):
            batch = celex_ids[start : start + DATES_BATCH]
            for row in self._bindings(
                _last_modified_sparql(batch), f"SPARQL dates at {start}"
            ):
                celex = row.get("celex", {}).get("value", "")
                moment = row.get("modified", {}).get("value", "")
                if (
                    celex
                    and moment
                    and (celex not in dates or is_later(moment, dates[celex]))
                ):
                    dates[celex] = moment
        return dates

    def fetch_celex_html(self, celex: str, lang: str = "NL") -> str:
        """The HTML of the act *celex*, from the CELLAR content server.

        The main eur-lex.europa.eu website is behind AWS WAF and returns HTTP 202
        bot-challenge responses to automated clients. CELLAR accepts content-negotiation
        requests without bot-protection and redirects to the actual document (XHTML).
        """
        lang_lower = lang.lower()
        headers = {
            "Accept": "text/html, application/xhtml+xml",
            "Accept-Language": f"{lang_lower}, {lang_lower}-{lang.upper()};q=0.9",
        }
        logger.debug("Fetching CELEX %s (%s) via CELLAR", celex, lang)
        return self.get_text(
            self._build_url(f"resource/celex/{celex}"),
            headers=headers,
            timeout=PAGE_TIMEOUT,
        )

    def _paged(
        self, sparql: Callable[[int], str], variable: str, context: str
    ) -> Iterator[str]:
        """The values of *variable* in the rows of the query *sparql* of an offset, page by
        page by offset until a page is short or ``MAX_RECORDS`` is reached.

        A page that fails raises: the endpoint answers HTTP 500 from offset 10000 on, and
        a list cut off there must not pass for the whole result.
        """
        for offset in range(0, MAX_RECORDS, _PAGE_SIZE):
            bindings = self._bindings(
                sparql(offset), f"SPARQL page ({context}) at offset {offset}"
            )
            for binding in bindings:
                value = binding.get(variable, {}).get("value", "")
                if value:
                    yield value
            if len(bindings) < _PAGE_SIZE:
                return

    def _bindings(self, query: str, page: str) -> list[dict[str, Any]]:
        """The rows of the answer to *query*; *page* names it in an error."""
        try:
            response = self.get(
                CELLAR_SPARQL,
                params={"query": query, "format": "application/sparql-results+json"},
                timeout=QUERY_TIMEOUT,
            )
        except requests.RequestException as exc:
            exc.add_note(page)
            raise
        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError(f"{page} is not JSON: {exc}") from exc
        rows: list[dict[str, Any]] = data.get("results", {}).get("bindings", [])
        return rows


def _batches(celex_ids: list[str]) -> Iterator[tuple[int, str]]:
    """``(start, values)`` of every ``CELEX_BATCH`` of *celex_ids*, the values as the list
    of a SPARQL ``IN``."""
    for start in range(0, len(celex_ids), CELEX_BATCH):
        batch = celex_ids[start : start + CELEX_BATCH]
        yield start, ", ".join(map(_sparql_string, batch))


def _sparql_string(value: str) -> str:
    """*value* as a SPARQL string literal."""
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return f'"{escaped}"'


# ── the SPARQL of one page; ``partial`` fixes all but the offset or the key ──


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


def _last_modified_sparql(celex_ids: list[str]) -> str:
    """The date of each act of *celex_ids*. CELLAR types the CELEX number ``xsd:string``,
    which a plain literal does not match."""
    values = " ".join(f"{_sparql_string(celex)}^^xsd:string" for celex in celex_ids)
    return (
        f"PREFIX cdm: <{_CDM}> PREFIX cmr: <{_CMR}> PREFIX xsd: <{_XSD}> "
        f"SELECT ?celex ?modified WHERE {{ VALUES ?celex {{ {values} }} "
        "?work cdm:resource_legal_id_celex ?celex ; cmr:lastModificationDate ?modified . }"
    )


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


def _implemented_acts_sparql(country_code: str, offset: int) -> str:
    return (
        f"PREFIX cdm: <{_CDM}> "
        "SELECT DISTINCT ?celex WHERE { "
        "?eu_act cdm:resource_legal_id_celex ?celex . "
        "?nim cdm:measure_national_implementing_implements_resource_legal ?eu_act ; "
        "cdm:measure_national_implementing_implemented_by_country "
        f"<{_COUNTRY}{country_code}> . "
        "} "
        f"ORDER BY ?celex LIMIT {_PAGE_SIZE} OFFSET {offset}"
    )


def _country_judgments_sparql(country_code: str, offset: int) -> str:
    return (
        f"PREFIX cdm: <{_CDM}> "
        "SELECT DISTINCT ?celex WHERE { "
        "?j a cdm:judgment ; "
        "cdm:resource_legal_id_celex ?celex ; "
        "cdm:case_law_relates_to_country "
        f"<{_COUNTRY}{country_code}> . "
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

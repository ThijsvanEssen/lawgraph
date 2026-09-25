"""Client for Wikidata: the Dutch cabinets.

Rijksoverheid describes the cabinets since 1945; for the ones before, Wikidata has every
item that is a ``Cabinet of the Netherlands`` (Q2479200) with its dates (P580 or P571, P582
or P576) and the cabinet before it (P155). One SPARQL query reads them.
"""

from __future__ import annotations

from typing import Any

from lawgraph.clients.base import BaseClient
from lawgraph.config.settings import WIKIDATA_SPARQL_ENDPOINT
from lawgraph.core.logging import get_logger

logger = get_logger(__name__)

# Wikidata asks every client to say who it is.
_USER_AGENT = "lawgraph (https://github.com/ThijsvanEssen/lawgraph)"
CABINET_OF_THE_NETHERLANDS = "Q2479200"
_ENTITY = "http://www.wikidata.org/entity/"

CABINETS_QUERY = f"""
SELECT ?cabinet ?cabinetLabel ?start ?startPrecision ?inception ?inceptionPrecision
       ?end ?endPrecision ?dissolved ?dissolvedPrecision ?previous WHERE {{
  ?cabinet wdt:P31 wd:{CABINET_OF_THE_NETHERLANDS} .
  OPTIONAL {{ ?cabinet p:P580/psv:P580 ?s .
             ?s wikibase:timeValue ?start ; wikibase:timePrecision ?startPrecision }}
  OPTIONAL {{ ?cabinet p:P571/psv:P571 ?i .
             ?i wikibase:timeValue ?inception ; wikibase:timePrecision ?inceptionPrecision }}
  OPTIONAL {{ ?cabinet p:P582/psv:P582 ?e .
             ?e wikibase:timeValue ?end ; wikibase:timePrecision ?endPrecision }}
  OPTIONAL {{ ?cabinet p:P576/psv:P576 ?d .
             ?d wikibase:timeValue ?dissolved ; wikibase:timePrecision ?dissolvedPrecision }}
  OPTIONAL {{ ?cabinet wdt:P155 ?previous }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "nl,mul,en". }}
}}
"""


def _value(row: dict[str, Any], name: str) -> str | None:
    cell = row.get(name)
    return cell.get("value") if isinstance(cell, dict) else None


def _date(value: str | None) -> str | None:
    """``1987-03-25`` of ``1987-03-25T00:00:00Z``."""
    return value[:10] if value else None


def _qid(value: str | None) -> str | None:
    return value.removeprefix(_ENTITY) if value else None


def _add(items: list[Any], item: Any) -> None:
    if item and item not in items:
        items.append(item)


def _keep_precise(
    record: dict[str, Any], field: str, row: dict[str, Any], names: tuple[str, ...]
) -> None:
    """Keep in *record* the most precise of the dates *names* of *row* (the first of them
    on a tie), and its precision in ``<field>_precision``."""
    for name in names:
        value = _date(_value(row, name))
        precision = int(_value(row, f"{name}Precision") or 0)
        if value and precision > (record[f"{field}_precision"] or 0):
            record[field] = value
            record[f"{field}_precision"] = precision


def group_cabinets(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The rows of ``CABINETS_QUERY`` as one record per cabinet: ``{id, name, from_date,
    from_date_precision, to_date, to_date_precision, previous}``. The start is the
    most precise of the start of its term (P580) and its inception (P571), the end of the
    end of its term (P582) and its dissolution (P576); a precision is Wikidata's
    (``PRECISION_DAY`` 11, a month 10, a year 9)."""
    cabinets: dict[str, dict[str, Any]] = {}
    for row in rows:
        cabinet = _qid(_value(row, "cabinet"))
        if not cabinet:
            continue
        record = cabinets.setdefault(
            cabinet,
            {
                "id": cabinet,
                "name": _value(row, "cabinetLabel"),
                "from_date": None,
                "from_date_precision": None,
                "to_date": None,
                "to_date_precision": None,
                "previous": [],
            },
        )
        _keep_precise(record, "from_date", row, ("start", "inception"))
        _keep_precise(record, "to_date", row, ("end", "dissolved"))
        _add(record["previous"], _qid(_value(row, "previous")))
    return sorted(cabinets.values(), key=lambda c: (c["from_date"] or "", c["id"]))


class WikidataClient(BaseClient):
    """Client for the Wikidata SPARQL endpoint."""

    def __init__(self, session=None) -> None:
        super().__init__(base_url=WIKIDATA_SPARQL_ENDPOINT, session=session)

    def cabinets(self) -> list[dict[str, Any]]:
        """Every Dutch cabinet, oldest first. Raises when the answer holds none."""
        cabinets = group_cabinets(self._select(CABINETS_QUERY))
        if not cabinets:
            raise RuntimeError(
                f"Wikidata returned no cabinets at all: the endpoint {self.base_url} "
                "or the way it records cabinets has changed."
            )
        logger.info("Wikidata: %d Dutch cabinets.", len(cabinets))
        return cabinets

    def _select(self, query: str) -> list[dict[str, Any]]:
        """The bindings a SPARQL query answers."""
        response = self._get_raw_absolute_with_retry(
            WIKIDATA_SPARQL_ENDPOINT,
            params={"query": query},
            timeout=120,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "application/sparql-results+json",
            },
        )
        return list(response.json().get("results", {}).get("bindings", []))

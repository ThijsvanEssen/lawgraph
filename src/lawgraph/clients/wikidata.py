"""Client for Wikidata: the posts people held in a Dutch cabinet.

The Tweede Kamer records no cabinet posts (``PersoonLoopbaan`` is a self-reported career,
empty for most ministers), and a signed paper names the function only on its date.
Wikidata has every post a person held in a cabinet of the Netherlands as a statement
``position held`` (P39) with the qualifier ``parliamentary group / cabinet`` (P5054), a start
(P580) and an end (P582). One SPARQL query reads them all, with the name and the date of
birth of each person, by which ``normalize wikidata`` finds the member. A second query
reads the parties of those people (``member of political party``, P102, with its dates),
by which ``normalize wikidata`` finds the parties of a cabinet. A third reads the cabinets
themselves: every item that is a ``Cabinet of the Netherlands``, with its dates (P580 or
P571, P582 or P576), its head (P6) and the cabinet before it (P155).
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

QUERY = f"""
SELECT ?person ?personLabel ?birth ?birthPrecision ?position ?positionLabel
       ?cabinet ?cabinetLabel ?start ?end WHERE {{
  ?person p:P39 ?held .
  ?held ps:P39 ?position ; pq:P5054 ?cabinet .
  ?cabinet wdt:P31 wd:{CABINET_OF_THE_NETHERLANDS} .
  OPTIONAL {{ ?held pq:P580 ?start }}
  OPTIONAL {{ ?held pq:P582 ?end }}
  OPTIONAL {{
    ?person p:P569/psv:P569 ?birthValue .
    ?birthValue wikibase:timeValue ?birth ; wikibase:timePrecision ?birthPrecision .
  }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "nl,mul,en". }}
}}
"""


PARTIES_QUERY = f"""
SELECT DISTINCT ?person ?party ?partyLabel ?short ?from ?until ?founded ?dissolved WHERE {{
  ?person p:P39 ?held .
  ?held pq:P5054 ?cabinet .
  ?cabinet wdt:P31 wd:{CABINET_OF_THE_NETHERLANDS} .
  ?person p:P102 ?membership .
  ?membership ps:P102 ?party .
  OPTIONAL {{ ?membership pq:P580 ?from }}
  OPTIONAL {{ ?membership pq:P582 ?until }}
  OPTIONAL {{ ?party wdt:P571 ?founded }}
  OPTIONAL {{ ?party wdt:P576 ?dissolved }}
  OPTIONAL {{ ?party wdt:P1813 ?short . FILTER(LANG(?short) IN ("nl", "mul")) }}
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "nl,mul,en". }}
}}
"""

CABINETS_QUERY = f"""
SELECT ?cabinet ?cabinetLabel ?start ?startPrecision ?inception ?inceptionPrecision
       ?end ?endPrecision ?dissolved ?dissolvedPrecision ?head ?previous WHERE {{
  ?cabinet wdt:P31 wd:{CABINET_OF_THE_NETHERLANDS} .
  OPTIONAL {{ ?cabinet p:P580/psv:P580 ?s .
             ?s wikibase:timeValue ?start ; wikibase:timePrecision ?startPrecision }}
  OPTIONAL {{ ?cabinet p:P571/psv:P571 ?i .
             ?i wikibase:timeValue ?inception ; wikibase:timePrecision ?inceptionPrecision }}
  OPTIONAL {{ ?cabinet p:P582/psv:P582 ?e .
             ?e wikibase:timeValue ?end ; wikibase:timePrecision ?endPrecision }}
  OPTIONAL {{ ?cabinet p:P576/psv:P576 ?d .
             ?d wikibase:timeValue ?dissolved ; wikibase:timePrecision ?dissolvedPrecision }}
  OPTIONAL {{ ?cabinet wdt:P6 ?head }}
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


def group_by_person(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The rows of the query as one record per person, each post once, oldest first.

    A person with two recorded dates of birth has a row per date: the most precise is kept.
    """
    people: dict[str, dict[str, Any]] = {}
    for row in rows:
        person = _qid(_value(row, "person"))
        if not person:
            continue
        record = people.setdefault(
            person,
            {
                "id": person,
                "name": _value(row, "personLabel"),
                "birth_date": None,
                "birth_precision": None,
                "posts": [],
            },
        )
        precision = int(_value(row, "birthPrecision") or 0)
        if precision > (record["birth_precision"] or 0):
            record["birth_date"] = _date(_value(row, "birth"))
            record["birth_precision"] = precision
        post = {
            "position_id": _qid(_value(row, "position")),
            "function": _value(row, "positionLabel"),
            "cabinet_id": _qid(_value(row, "cabinet")),
            "cabinet": _value(row, "cabinetLabel"),
            "from_date": _date(_value(row, "start")),
            "to_date": _date(_value(row, "end")),
        }
        if post not in record["posts"]:
            record["posts"].append(post)
    for record in people.values():
        record["posts"].sort(key=lambda p: (p["from_date"] or "", p["function"] or ""))
    return list(people.values())


def _add(items: list[Any], item: Any) -> None:
    if item and item not in items:
        items.append(item)


def party_memberships(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """The rows of ``PARTIES_QUERY`` as the parties of each person (Q-id -> parties):
    ``{id, name, short, from_date, to_date, founded, dissolved}``, one per membership."""
    parties: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        person, party = _qid(_value(row, "person")), _qid(_value(row, "party"))
        if not person or not party:
            continue
        _add(
            parties.setdefault(person, []),
            {
                "id": party,
                "name": _value(row, "partyLabel"),
                "short": _value(row, "short"),
                "from_date": _date(_value(row, "from")),
                "to_date": _date(_value(row, "until")),
                "founded": _date(_value(row, "founded")),
                "dissolved": _date(_value(row, "dissolved")),
            },
        )
    return parties


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
    from_date_precision, to_date, to_date_precision, heads, previous}``. The start is the
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
                "heads": [],
                "previous": [],
            },
        )
        _keep_precise(record, "from_date", row, ("start", "inception"))
        _keep_precise(record, "to_date", row, ("end", "dissolved"))
        _add(record["heads"], _qid(_value(row, "head")))
        _add(record["previous"], _qid(_value(row, "previous")))
    return sorted(cabinets.values(), key=lambda c: (c["from_date"] or "", c["id"]))


class WikidataClient(BaseClient):
    """Client for the Wikidata SPARQL endpoint."""

    def __init__(self, session=None) -> None:
        super().__init__(base_url=WIKIDATA_SPARQL_ENDPOINT, session=session)

    def cabinet_posts(self) -> list[dict[str, Any]]:
        """Every person who held a post in a Dutch cabinet, with those posts.

        Raises when the request fails, and when the answer holds nobody: the endpoint or
        the way Wikidata records cabinets has then changed.
        """
        people = group_by_person(self._select(QUERY))
        parties = party_memberships(self._select(PARTIES_QUERY))
        for person in people:
            person["parties"] = parties.get(person["id"], [])
        if not people:
            raise RuntimeError(
                f"Wikidata returned no cabinet posts at all: the endpoint {self.base_url} "
                "or the way it records cabinets has changed."
            )
        logger.info(
            "Wikidata: %d posts of %d people in Dutch cabinets.",
            sum(len(p["posts"]) for p in people),
            len(people),
        )
        return people

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

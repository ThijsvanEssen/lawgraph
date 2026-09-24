"""Client for Wikidata: the posts people held in a Dutch cabinet.

The Tweede Kamer records no cabinet posts (``PersoonLoopbaan`` is a self-reported career,
empty for most ministers), and a signed paper names the function only on its date.
Wikidata has every post a person held in a cabinet of the Netherlands as a statement
``position held`` (P39) with the qualifier ``parliamentary group / cabinet`` (P5054), a start
(P580) and an end (P582). One SPARQL query reads them all, with the name and the date of
birth of each person, by which ``normalize wikidata`` finds the member.
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
  SERVICE wikibase:label {{ bd:serviceParam wikibase:language "nl,en". }}
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


class WikidataClient(BaseClient):
    """Client for the Wikidata SPARQL endpoint."""

    def __init__(self, session=None) -> None:
        super().__init__(base_url=WIKIDATA_SPARQL_ENDPOINT, session=session)

    def cabinet_posts(self) -> list[dict[str, Any]]:
        """Every person who held a post in a Dutch cabinet, with those posts.

        Raises when the request fails, and when the answer holds nobody: the endpoint or
        the way Wikidata records cabinets has then changed.
        """
        response = self._get_raw_absolute_with_retry(
            WIKIDATA_SPARQL_ENDPOINT,
            params={"query": QUERY},
            timeout=120,
            headers={
                "User-Agent": _USER_AGENT,
                "Accept": "application/sparql-results+json",
            },
        )
        rows = response.json().get("results", {}).get("bindings", [])
        people = group_by_person(rows)
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

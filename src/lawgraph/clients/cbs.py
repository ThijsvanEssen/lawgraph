"""Client for the open data of the CBS (StatLine, ``opendata.cbs.nl``): the catalogue, and the
OData of a table.

The CBS publishes a table "Gebieden in Nederland <year>" each year: every municipality of that
year with the areas it lies in (arrondissement and ressort among them, as the Wet op de
rechterlijke indeling draws them). A table answers its columns (``DataProperties``: a key per
column, grouped under a title such as "Arrondissementen (rechtsgebieden)") and its rows
(``TypedDataSet``); the key of a column differs from year to year, its group title does not.
The open data of the CBS falls under CC BY 4.0.
"""

from __future__ import annotations

import re
from typing import Any

import requests

from lawgraph.clients.base import BaseClient
from lawgraph.config.sources import CBS
from lawgraph.core.logging import get_logger

logger = get_logger(__name__)

CATALOG_TABLES = "ODataCatalog/Tables"
# The title of the yearly table of areas, its year in the group.
REGIONS_TITLE = re.compile(r"^Gebieden in Nederland (\d{4})$")


class CbsClient(BaseClient):
    """Client for the catalogue and the tables of StatLine."""

    def __init__(self, session: requests.Session | None = None) -> None:
        super().__init__(base_url=CBS.base_url, session=session)

    def region_tables(self) -> list[dict[str, Any]]:
        """``{identifier, year, modified}`` of every table "Gebieden in Nederland <year>" the
        catalogue lists, oldest first. Raises when it lists none."""
        listed = self._values(
            self._build_url(CATALOG_TABLES),
            {
                "$format": "json",
                "$filter": "substringof('Gebieden in Nederland',Title)",
                "$select": "Identifier,Title,Modified",
            },
        )
        tables = [
            {
                "identifier": t["Identifier"],
                "year": int(m.group(1)),
                "modified": str(t.get("Modified") or "")[:10],
            }
            for t in listed
            if (m := REGIONS_TITLE.match(str(t.get("Title") or "").strip()))
        ]
        if not tables:
            raise RuntimeError(
                "The CBS catalogue lists no table of areas: it has changed."
            )
        return sorted(tables, key=lambda t: t["year"])

    def table(self, identifier: str) -> tuple[str, dict[str, Any]]:
        """``(url, {properties, rows})`` of the table *identifier*: its columns and every row."""
        base = self._build_url(f"ODataApi/odata/{identifier}")
        properties = self._values(f"{base}/DataProperties", {"$format": "json"})
        url = f"{base}/TypedDataSet"
        rows = self._values(url, {"$format": "json"})
        logger.info(
            "CBS %s: %d columns, %d rows.", identifier, len(properties), len(rows)
        )
        return url, {"properties": properties, "rows": rows}

    def _values(self, url: str, params: dict[str, str] | None) -> list[dict[str, Any]]:
        """Every ``value`` of an OData answer, following ``odata.nextLink``."""
        values: list[dict[str, Any]] = []
        next_url: str | None = url
        while next_url:
            answer = self.get_json(next_url, params=params)
            values.extend(answer.get("value") or [])
            next_url, params = answer.get("odata.nextLink"), None
        return values

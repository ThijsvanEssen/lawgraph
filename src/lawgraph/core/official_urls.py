"""The official page of a law, an article or a publication.

- A BWB regulation is on wetten.overheid.nl: ``/{BWB}`` for the version in force, ``/{BWB}/
  {date}`` for the version valid on that day. An article is addressed by its JCI
  (``jci1.3:c:{BWB}&artikel={nr}``, with ``&g={date}`` for a version); an article without a
  number (the Algemene bepaling of the Grondwet) or in an annex has no JCI address of its own
  and links to its regulation.
- An EU act is on EUR-Lex by its CELEX number, in Dutch.
- An amending publication (a node with ``publication_kind``, ``_year`` and ``_number``) is its
  page on zoek.officielebekendmakingen.nl, as below.
- A treaty is on the Verdragenbank: the page its record names (``props.uri``).
- A publication in the Staatsblad, Staatscourant or Tractatenblad is on
  zoek.officielebekendmakingen.nl by its identifier (``stb-2022-332``), from 1995, when that
  site begins.
"""

from __future__ import annotations

import re
from typing import Any

WETTEN = "https://wetten.overheid.nl"
EUR_LEX = "https://eur-lex.europa.eu/legal-content/NL/TXT/?uri=CELEX:{celex}"
OFFICIELE_BEKENDMAKINGEN = "https://zoek.officielebekendmakingen.nl/{identifier}.html"
# The first year zoek.officielebekendmakingen.nl holds.
FIRST_PUBLICATION_YEAR = 1995

# A regulation of the BWB (not the pseudo-id ``ECHR-CONVENTION``).
_BWB_ID = re.compile(r"^BWB[RV]\d{7}$")
# An article number the JCI can address: "7", "7:658", "1.1", "12a", "5.2.3a".
_JCI_NUMBER = re.compile(r"^[0-9][0-9A-Za-z.:]*$")


def instrument_url(props: dict[str, Any], *, on: str | None = None) -> str | None:
    """The official page of an instrument (its props), the version valid *on* that day
    for a BWB regulation; None for one without a page."""
    bwb_id = props.get("bwb_id")
    if isinstance(bwb_id, str) and _BWB_ID.match(bwb_id):
        return f"{WETTEN}/{bwb_id}/{on}" if on else f"{WETTEN}/{bwb_id}"
    if props.get("celex"):
        return EUR_LEX.format(celex=props["celex"])
    kind, year = props.get("publication_kind"), props.get("publication_year")
    if kind and year and props.get("publication_number"):  # Stb. 2019, 33
        identifier = f"{str(kind).lower()}-{year}-{props['publication_number']}"
        return publication_url({"id": identifier, "year": year})
    uri = props.get("uri")
    return uri if isinstance(uri, str) and uri.startswith("https://") else None


def article_url(
    bwb_id: str | None, number: str | None, *, on: str | None = None
) -> str | None:
    """The official page of article *number* of the BWB regulation *bwb_id*, of the
    version valid *on* that day; the regulation's page for an article the JCI cannot
    address; None outside the BWB."""
    if not bwb_id or not _BWB_ID.match(bwb_id):
        return None
    if not number or not _JCI_NUMBER.match(number):
        return instrument_url({"bwb_id": bwb_id}, on=on)
    url = f"{WETTEN}/jci1.3:c:{bwb_id}&artikel={number}"
    return f"{url}&g={on}" if on else url


def publication_url(publication: dict[str, Any] | None) -> str | None:
    """The page of a publication (``Publication.to_dict()``) on
    zoek.officielebekendmakingen.nl; None before 1995 or without an identifier."""
    if not publication or not publication.get("id"):
        return None
    year = publication.get("year")
    if not isinstance(year, int) or year < FIRST_PUBLICATION_YEAR:
        return None
    return OFFICIELE_BEKENDMAKINGEN.format(identifier=publication["id"])

"""What the search of each type reads (``SEARCHED``), so an answer without hits does not read
as "not there": the fields its words are found in, as one closed list of words
(``Searched``), and its text ``none`` when the type has one its search does not read.

Derived from what the search reads: ``SearchType.fields`` (``SEARCH_FIELDS``),
``SEARCH_WORDS`` and the ``search_names`` column of a type searched by its names; the text
from the props schema of the type (``core.props``)."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from lawgraph.core.completeness import Coverage, Part
from lawgraph.core.models import COLLECTION_SPECS
from lawgraph.db.queries.search.spec import SearchType
from lawgraph.db.queries.search.types import SEARCHES
from lawgraph.db.schema import COLUMNS, SEARCH_WORDS


class Searched(StrEnum):
    """What of a record its words are found in, in the order an answer lists them."""

    TITLE = "title"  # its title, heading or name as shown, or what a vote was on
    NAME = "name"  # the names it goes by: parties, aliases, abbreviations, persons
    NUMBER = "number"  # its number or identifier (ECLI, BWB id, dossier number)
    SUMMARY = "summary"  # its summary (the inhoudsindicatie of a judgment)
    TEXT = "text"  # its text
    KIND = "kind"  # its kind (Motie, Wetgeving)


# The word of each field a search reads.
FIELD_SEARCHED: dict[str, Searched] = {
    "display_name": Searched.TITLE,
    "title": Searched.TITLE,
    "citation_title": Searched.TITLE,
    "official_title": Searched.TITLE,
    "heading": Searched.TITLE,
    "breadcrumb.title": Searched.TITLE,
    "subject": Searched.TITLE,
    "name": Searched.NAME,
    "names": Searched.NAME,
    "short_title": Searched.NAME,
    "aliases": Searched.NAME,
    "abbreviation": Searched.NAME,
    "search_names": Searched.NAME,
    "number": Searched.NUMBER,
    "article_number": Searched.NUMBER,
    "bwb_id": Searched.NUMBER,
    "ecli": Searched.NUMBER,
    "appno": Searched.NUMBER,
    "external_id": Searched.NUMBER,
    "summary": Searched.SUMMARY,
    "text": Searched.TEXT,
    "kind": Searched.KIND,
}

_NAMES = "search_names"


def _fields(kind: SearchType) -> list[str]:
    """The fields the search of *kind* reads."""
    columns = {column.name for column in COLUMNS.get(kind.table, ())}
    return [
        *kind.fields,
        *SEARCH_WORDS.get(kind.table, ()),
        *([_NAMES] if _NAMES in columns else []),
    ]


def searched(kind: SearchType) -> dict[str, Any]:
    """``{fields, completeness}`` of the search of *kind*: the words it is found by, and
    ``completeness.text``: ``done`` when its search reads its text, ``none`` when the
    type has a text its search does not read; a type without a text has no ``text``."""
    words = {FIELD_SEARCHED[field] for field in _fields(kind)}
    completeness: dict[str, Any] = {}
    if Part.TEXT.value in COLLECTION_SPECS[kind.table].props_schema.model_fields:
        state = Coverage.DONE if Searched.TEXT in words else Coverage.NONE
        completeness[Part.TEXT.value] = {"state": state.value}
    return {
        "fields": [word.value for word in Searched if word in words],
        "completeness": completeness,
    }


SEARCHED: dict[str, dict[str, Any]] = {
    table: searched(kind) for table, kind in SEARCHES.items()
}

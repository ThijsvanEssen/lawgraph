"""LawGraph runtime configuration helpers.

Structural changes:
- Centralize collection, Arango and client endpoints so no module contains raw constants.
- Provide env-aware defaults so pipelines/clients can stay consistent.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def _env_list(name: str, default: tuple[str, ...]) -> list[str]:
    """Return a cleaned list for a comma-separated env variable, falling back to default."""
    raw_value = os.getenv(name)
    if raw_value:
        return [segment.strip() for segment in raw_value.split(",") if segment.strip()]
    return list(default)


DEFAULT_DOCUMENT_COLLECTIONS: tuple[str, ...] = (
    "instruments",
    "instrument_articles",
    "procedures",
    "publications",
    "judgments",
    "topics",
    "raw_sources",
)

DEFAULT_EDGE_COLLECTIONS: tuple[str, ...] = ("edges_strict", "edges_semantic")

DOCUMENT_COLLECTIONS: list[str] = _env_list(
    "LAWGRAPH_DOCUMENT_COLLECTIONS", DEFAULT_DOCUMENT_COLLECTIONS
)
EDGE_COLLECTIONS: list[str] = _env_list("LAWGRAPH_EDGE_COLLECTIONS", DEFAULT_EDGE_COLLECTIONS)

DEFAULT_ARANGO_URL = "http://localhost:8529"
DEFAULT_ARANGO_DB_NAME = "lawgraph"
DEFAULT_ARANGO_USER = "root"
DEFAULT_ARANGO_PASSWORD = ""

ARANGO_URL = os.getenv("ARANGO_URL", DEFAULT_ARANGO_URL)
ARANGO_DB_NAME = os.getenv("ARANGO_DB_NAME", DEFAULT_ARANGO_DB_NAME)
ARANGO_USER = os.getenv("ARANGO_USER", DEFAULT_ARANGO_USER)
ARANGO_PASSWORD = os.getenv("ARANGO_PASSWORD", DEFAULT_ARANGO_PASSWORD)

DEFAULT_BWB_BASE = "https://wetten.overheid.nl/"
DEFAULT_EU_BASE = "https://eur-lex.europa.eu/"
DEFAULT_RECHTSPRAAK_BASE = "https://data.rechtspraak.nl/"
DEFAULT_TK_BASE = "https://gegevensmagazijn.tweedekamer.nl/OData/v4/2.0/"

BWB_BASE_URL = os.getenv("BWB_BASE", DEFAULT_BWB_BASE)
EU_BASE_URL = os.getenv("EURLEX_BASE", DEFAULT_EU_BASE)
RECHTSPRAAK_BASE_URL = os.getenv("RECHTSPRAAK_BASE", DEFAULT_RECHTSPRAAK_BASE)
TK_BASE_URL = os.getenv("TK_API_BASE", DEFAULT_TK_BASE)

DEFAULT_BWB_SRU_ENDPOINT = "https://zoekservice.overheid.nl/sru/Search"
BWB_SRU_ENDPOINT = os.getenv("BWB_SRU_ENDPOINT", DEFAULT_BWB_SRU_ENDPOINT)


SOURCE_TK = "tk"
SOURCE_RECHTSPRAAK = "rechtspraak"
SOURCE_EURLEx = "eurlex"
SOURCE_BWB = "bwb"

RAW_KIND_TK_ZAAK = "tk-zaak"
RAW_KIND_TK_DOCUMENTVERSIE = "tk-documentversie"
RAW_KIND_RS_INDEX = "rs-index"
RAW_KIND_RS_CONTENT = "rs-content"
RAW_KIND_EU_CELEX = "eu-celex-html"
RAW_KIND_BWB_REGELING = "bwb-regeling-xml"
RAW_KIND_BWB_TOESTAND = "bwb-toestand-xml"

RAW_SOURCE_KINDS: dict[str, tuple[str, ...]] = {
    SOURCE_TK: (RAW_KIND_TK_ZAAK, RAW_KIND_TK_DOCUMENTVERSIE),
    SOURCE_RECHTSPRAAK: (RAW_KIND_RS_INDEX, RAW_KIND_RS_CONTENT),
    SOURCE_EURLEx: (RAW_KIND_EU_CELEX,),
    SOURCE_BWB: (RAW_KIND_BWB_REGELING, RAW_KIND_BWB_TOESTAND),
}

COLLECTION_INSTRUMENTS = "instruments"
COLLECTION_INSTRUMENT_ARTICLES = "instrument_articles"
COLLECTION_PROCEDURES = "procedures"
COLLECTION_PUBLICATIONS = "publications"
COLLECTION_JUDGMENTS = "judgments"
COLLECTION_TOPICS = "topics"
COLLECTION_RAW_SOURCES = "raw_sources"

RELATION_PART_OF_INSTRUMENT = "PART_OF_INSTRUMENT"
RELATION_PART_OF_PROCEDURE = "PART_OF_PROCEDURE"
RELATION_RELATED_TOPIC = "RELATED_TOPIC"

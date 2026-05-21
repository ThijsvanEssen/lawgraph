"""LawGraph runtime configuration — env-var derived values only.

Domain constants (relation types, collection names, source IDs) live in constants.py.
"""

from __future__ import annotations

import os

from lawgraph.core.logging import get_logger

from lawgraph.config.constants import (
    COLLECTION_ACTIVITEITEN,
    COLLECTION_COMMISSIES,
    COLLECTION_EDGE_STATUS_LOG,
    COLLECTION_FRACTIES,
    COLLECTION_INSTRUMENT_ARTICLE_VERSIONS,
    COLLECTION_INSTRUMENT_ARTICLES,
    COLLECTION_INSTRUMENT_VERSIONS,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    COLLECTION_KAMERSTUKDOSSIERS,
    COLLECTION_LEDEN,
    COLLECTION_PROCEDURES,
    COLLECTION_PUBLICATIONS,
    COLLECTION_RAW_SOURCES,
    COLLECTION_STEMMINGEN,
    COLLECTION_TOEZEGGINGEN,
    COLLECTION_TOPICS,
    COLLECTION_WATCHES,
)

logger = get_logger(__name__)


def _env_list(name: str, default: tuple[str, ...]) -> list[str]:
    raw_value = os.getenv(name)
    if raw_value:
        return [s.strip() for s in raw_value.split(",") if s.strip()]
    return list(default)


# ── Collections (env-var driven) ──────────────────────────────────────────────

DEFAULT_DOCUMENT_COLLECTIONS: tuple[str, ...] = (
    COLLECTION_INSTRUMENTS,
    COLLECTION_INSTRUMENT_ARTICLES,
    COLLECTION_INSTRUMENT_VERSIONS,
    COLLECTION_INSTRUMENT_ARTICLE_VERSIONS,
    COLLECTION_PROCEDURES,
    COLLECTION_PUBLICATIONS,
    COLLECTION_JUDGMENTS,
    COLLECTION_TOPICS,
    COLLECTION_RAW_SOURCES,
    COLLECTION_KAMERSTUKDOSSIERS,
    COLLECTION_ACTIVITEITEN,
    COLLECTION_STEMMINGEN,
    COLLECTION_TOEZEGGINGEN,
    COLLECTION_COMMISSIES,
    COLLECTION_LEDEN,
    COLLECTION_FRACTIES,
    COLLECTION_EDGE_STATUS_LOG,
    COLLECTION_WATCHES,
)

DOCUMENT_COLLECTIONS: list[str] = _env_list(
    "LAWGRAPH_DOCUMENT_COLLECTIONS", DEFAULT_DOCUMENT_COLLECTIONS
)

# Single unified edge collection (env-var overridable).
COLLECTION_EDGES = os.getenv("LAWGRAPH_EDGE_COLLECTION", "edges")

# ── ArangoDB connection ───────────────────────────────────────────────────────

ARANGO_URL = os.getenv("ARANGO_URL", "http://localhost:8529")
ARANGO_DB_NAME = os.getenv("ARANGO_DB_NAME", "lawgraph")
ARANGO_USER = os.getenv("ARANGO_USER", "root")
ARANGO_PASSWORD = os.getenv("ARANGO_PASSWORD", "")
ARANGO_REQUEST_TIMEOUT = 620

# ── External API base URLs ────────────────────────────────────────────────────

BWB_BASE_URL = os.getenv("BWB_BASE", "https://wetten.overheid.nl/")
EURLEX_BASE_URL = os.getenv("EURLEX_BASE", "https://eur-lex.europa.eu/")
RECHTSPRAAK_BASE_URL = os.getenv("RECHTSPRAAK_BASE", "https://data.rechtspraak.nl/")
TK_BASE_URL = os.getenv(
    "TK_API_BASE", "https://gegevensmagazijn.tweedekamer.nl/OData/v4/2.0/"
)
TK_DOCUMENT_RESOURCE_URL = TK_BASE_URL.rstrip("/") + "/Document({external_id})/resource"

BWB_SRU_ENDPOINT = os.getenv(
    "BWB_SRU_ENDPOINT", "https://zoekservice.overheid.nl/sru/Search"
)

EURLEX_SPARQL_ENDPOINT = os.getenv(
    "EURLEX_SPARQL_ENDPOINT", "https://publications.europa.eu/webapi/rdf/sparql"
)

STAATSBLAD_SRU_ENDPOINT = os.getenv(
    "STAATSBLAD_SRU_ENDPOINT", "https://sru.officielebekendmakingen.nl/sru/Search"
)
STAATSBLAD_REPO_BASE = os.getenv(
    "STAATSBLAD_REPO_BASE", "https://repository.overheid.nl"
)

STAATSCOURANT_SRU_ENDPOINT = os.getenv(
    "STAATSCOURANT_SRU_ENDPOINT", "https://sru.officielebekendmakingen.nl/sru/Search"
)

EERSTEKAMER_BASE_URL = os.getenv(
    "EERSTEKAMER_BASE", "https://gegevensmagazijn.eerstekamer.nl/OData/v4/2.0/"
)

ECHR_HUDOC_BASE_URL = os.getenv("ECHR_HUDOC_BASE", "https://hudoc.echr.coe.int")

VERDRAGENBANK_SPARQL_ENDPOINT = os.getenv(
    "VERDRAGENBANK_SPARQL", "https://linkeddata.overheid.nl/front/portal/sparql"
)

# ── Semantic confidence overrides ─────────────────────────────────────────────


def get_confidence_override(pattern_name: str, default: float) -> float:
    """Return a per-pattern confidence value, overridable via env var.

    Env var: LAWGRAPH_CONFIDENCE_<PATTERN_NAME_UPPER>
    Example: LAWGRAPH_CONFIDENCE_BWB_EXPLICIT=0.95
    """
    env_key = f"LAWGRAPH_CONFIDENCE_{pattern_name.upper()}"
    raw = os.getenv(env_key)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning(
            "Invalid value for env var %s=%r; using default %s.", env_key, raw, default
        )
        return default

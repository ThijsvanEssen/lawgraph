"""Runtime configuration: every value that comes from the environment.

Importing this module loads ``.env`` (searched from the working directory upwards), so any
code that reads a setting sees it. Variables already set in the process environment win over
``.env``. No other module reads ``os.environ``.
"""

from __future__ import annotations

import logging
import os

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(usecwd=True))

logger = logging.getLogger(__name__)


def _env_list(name: str, default: str = "") -> list[str]:
    return [
        item.strip() for item in os.getenv(name, default).split(",") if item.strip()
    ]


# ── Logging ───────────────────────────────────────────────────────────────────

LOG_LEVEL = os.getenv("LAWGRAPH_LOG_LEVEL", "INFO").upper()
LOG_JSON = os.getenv("LAWGRAPH_LOG_FORMAT", "").lower() == "json"
LOG_NO_COLOR = os.getenv("NO_COLOR") is not None
# Every log line also goes to this file, as plain lines. It is what makes a log file and the
# live progress of a terminal go together: piped into `tee`, stderr is no terminal any more.
LOG_FILE = os.getenv("LAWGRAPH_LOG_FILE")

# ── ArangoDB connection ───────────────────────────────────────────────────────

ARANGO_URL = os.getenv("ARANGO_URL", "http://localhost:8529")
ARANGO_DB_NAME = os.getenv("ARANGO_DB_NAME", "lawgraph")
ARANGO_USER = os.getenv("ARANGO_USER", "root")
ARANGO_PASSWORD = os.getenv("ARANGO_PASSWORD", "")
# Slightly above the 600 s a writing query may take (db/store.py), so the server times out
# before the client.
ARANGO_REQUEST_TIMEOUT = 620

# ── External sources ──────────────────────────────────────────────────────────

BWB_BASE_URL = os.getenv("BWB_BASE", "https://wetten.overheid.nl/")
BWB_SRU_ENDPOINT = os.getenv(
    "BWB_SRU_ENDPOINT", "https://zoekservice.overheid.nl/sru/Search"
)
EURLEX_BASE_URL = os.getenv("EURLEX_BASE", "https://eur-lex.europa.eu/")
EURLEX_SPARQL_ENDPOINT = os.getenv(
    "EURLEX_SPARQL_ENDPOINT", "https://publications.europa.eu/webapi/rdf/sparql"
)
RECHTSPRAAK_BASE_URL = os.getenv("RECHTSPRAAK_BASE", "https://data.rechtspraak.nl/")
TK_BASE_URL = os.getenv(
    "TK_API_BASE", "https://gegevensmagazijn.tweedekamer.nl/OData/v4/2.0/"
)
TK_DOCUMENT_RESOURCE_URL_TEMPLATE = (
    TK_BASE_URL.rstrip("/") + "/Document({external_id})/resource"
)
# Staatsblad and Staatscourant share one SRU server and one repository; the collection is
# chosen by a query parameter (x-connection) at request time.
STAATSBLAD_SRU_ENDPOINT = os.getenv(
    "STAATSBLAD_SRU_ENDPOINT", "https://repository.overheid.nl/sru"
)
STAATSBLAD_REPO_BASE = os.getenv(
    "STAATSBLAD_REPO_BASE", "https://repository.overheid.nl"
)
STAATSCOURANT_SRU_ENDPOINT = os.getenv(
    "STAATSCOURANT_SRU_ENDPOINT", "https://repository.overheid.nl/sru"
)
STAATSCOURANT_REPO_BASE = os.getenv(
    "STAATSCOURANT_REPO_BASE", "https://repository.overheid.nl"
)
EERSTEKAMER_SRU_ENDPOINT = os.getenv(
    "EERSTEKAMER_SRU", "https://repository.overheid.nl/sru"
)
KAMERSTUK_REPO_BASE = os.getenv("KAMERSTUK_REPO_BASE", "https://repository.overheid.nl")
ECHR_HUDOC_BASE_URL = os.getenv("ECHR_HUDOC_BASE", "https://hudoc.echr.coe.int")
VERDRAGENBANK_SRU_ENDPOINT = os.getenv(
    "VERDRAGENBANK_SRU", "https://repository.overheid.nl/sru"
)

# ── Pipelines ─────────────────────────────────────────────────────────────────

BWB_IDS = _env_list("BWB_IDS")
EURLEX_MAX_ARTICLE_NUMBER = int(os.getenv("EURLEX_MAX_ARTICLE_NUMBER", "200"))


def skip_step(phase: str, pipeline_name: str) -> bool:
    """True when ``LAWGRAPH_<PHASE>_SKIP_<NAME>=true`` leaves a pipeline out of ``<phase> all``."""
    return os.getenv(skip_variable(phase, pipeline_name), "").strip().lower() == "true"


def skip_variable(phase: str, pipeline_name: str) -> str:
    """``LAWGRAPH_NORMALIZE_SKIP_TK_DOSSIERS`` for ``normalize tk-dossiers``."""
    return f"LAWGRAPH_{phase.upper()}_SKIP_{pipeline_name.upper().replace('-', '_')}"


def confidence_override(pattern_name: str, default: float) -> float:
    """Confidence of one detection pattern: ``LAWGRAPH_CONFIDENCE_<PATTERN>`` or *default*."""
    variable = f"LAWGRAPH_CONFIDENCE_{pattern_name.upper()}"
    raw = os.getenv(variable)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Invalid %s=%r; using default %s.", variable, raw, default)
        return default


# ── API ───────────────────────────────────────────────────────────────────────

API_HOST = os.getenv("LAWGRAPH_API_HOST", "127.0.0.1")
API_PORT = int(os.getenv("LAWGRAPH_API_PORT", "8000"))
API_ALLOWED_ORIGINS = _env_list(
    "LAWGRAPH_ALLOWED_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174",
)
API_RATE_LIMIT_CALLS = int(os.getenv("LAWGRAPH_RATE_LIMIT_CALLS", "200"))
API_RATE_LIMIT_PERIOD = float(os.getenv("LAWGRAPH_RATE_LIMIT_PERIOD", "60"))
API_TRUSTED_PROXIES = frozenset(_env_list("LAWGRAPH_TRUSTED_PROXIES"))
API_CACHE_TTL = float(os.getenv("LAWGRAPH_CACHE_TTL", "60"))
API_CACHE_MAXSIZE = int(os.getenv("LAWGRAPH_CACHE_MAXSIZE", "512"))


def curation_api_key() -> str | None:
    """Shared key for the curation endpoint; curation is disabled when unset."""
    return os.getenv("LAWGRAPH_CURATION_API_KEY") or None

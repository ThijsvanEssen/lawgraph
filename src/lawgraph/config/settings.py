"""Runtime configuration: every value that comes from the environment.

Importing this module loads ``.env`` (searched from the working directory upwards), so any
code that reads a setting sees it. Variables already set in the process environment win over
``.env``. No other module reads ``os.environ``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from urllib.parse import quote

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(usecwd=True))

logger = logging.getLogger(__name__)


def _env_list(name: str, default: str = "") -> list[str]:
    return [
        item.strip() for item in os.getenv(name, default).split(",") if item.strip()
    ]


def _env_positive_int(name: str, default: int) -> int:
    value = int(os.getenv(name) or default)
    if value <= 0:
        raise ValueError(f"{name} must be a positive number, not {value}")
    return value


# ── Logging ───────────────────────────────────────────────────────────────────

LOG_LEVEL = os.getenv("LAWGRAPH_LOG_LEVEL", "INFO").upper()
LOG_JSON = os.getenv("LAWGRAPH_LOG_FORMAT", "").lower() == "json"
LOG_NO_COLOR = os.getenv("NO_COLOR") is not None
# Every log line also goes to this file, as plain lines. It is what makes a log file and the
# live progress of a terminal go together: piped into `tee`, stderr is no terminal any more.
LOG_FILE = os.getenv("LAWGRAPH_LOG_FILE")

# ── PostgreSQL connection ─────────────────────────────────────────────────────

# The server (``postgresql://user:password@host:port``) and the database on it; the store
# creates the database when it is missing and the user may. Without a URL: the server of
# docker-compose.yml, with the password it was given (LAWGRAPH_DB_PASSWORD).
DB_PASSWORD = os.getenv("LAWGRAPH_DB_PASSWORD", "")
DB_URL = os.getenv(
    "LAWGRAPH_DB_URL",
    f"postgresql://lawgraph{':' + quote(DB_PASSWORD, safe='') if DB_PASSWORD else ''}"
    "@localhost:5432",
)
DB_NAME = os.getenv("LAWGRAPH_DB_NAME", "lawgraph")
# Connections of one process: the API serves this many requests at once.
DB_POOL_SIZE = int(os.getenv("LAWGRAPH_DB_POOL_SIZE", "8"))
# Connections of one process for what the API computes in the background (its warm-up and
# the answers it keeps per data version), apart from the ones above: a slow computation
# never keeps a request waiting for a connection. Opened when first needed.
DB_BACKGROUND_POOL_SIZE = _env_positive_int("LAWGRAPH_DB_BACKGROUND_POOL_SIZE", 2)
# A database whose strings sort by another collation than the schema's ICU collation is
# refused; this names the one let through anyway, for the dump and restore that replaces it
# (``libc en_US.utf8``, as the refusal names it).
ALLOW_COLLATION = os.getenv("LAWGRAPH_ALLOW_COLLATION", "").strip()
# The longest a statement that writes may run (``statement_timeout``, db/store.py), in
# milliseconds: a ceiling that is never off. A build on a slow disk raises it.
WRITE_TIMEOUT_MS = _env_positive_int("LAWGRAPH_WRITE_TIMEOUT_MS", 600_000)
# The longest one statement that reads may run, in milliseconds (a FETCH of a streamed
# read is a statement of its own): a ceiling for a plan that never ends, never off.
READ_TIMEOUT_MS = _env_positive_int("LAWGRAPH_READ_TIMEOUT_MS", 10_800_000)
# Every this many minutes a running step logs how long it runs and the statements of its
# process that have run for over a minute (``pipelines/watchdog.py``).
WATCHDOG_MINUTES = _env_positive_int("LAWGRAPH_WATCHDOG_MINUTES", 10)

# ── ArangoDB connection ───────────────────────────────────────────────────────

ARANGO_URL = os.getenv("ARANGO_URL", "http://localhost:8529")
ARANGO_DB_NAME = os.getenv("ARANGO_DB_NAME", "lawgraph")
ARANGO_USER = os.getenv("ARANGO_USER", "root")
ARANGO_PASSWORD = os.getenv("ARANGO_PASSWORD", "")
# Slightly above the 600 s a writing query may take (db/store.py), so the server times out
# before the client.
ARANGO_REQUEST_TIMEOUT = 620

# ArangoDB Community stops a server whose dataset reaches 100 GiB (two days of warnings, two
# days read-only, then shut down). `lawgraph check` fails from this size on, well before that.
DB_SIZE_ALERT_GIB = float(os.getenv("LAWGRAPH_DB_SIZE_ALERT_GIB", "70"))

# ── Payload store ─────────────────────────────────────────────────────────────

# Where the text payloads (XML, HTML) of raw records are kept (db/payloads.py): a directory
# (file:///path) or an S3 bucket (s3://bucket/prefix). The S3 values are those of LeafCloud's
# object storage when the bucket is there: endpoint https://leafcloud.store, region
# europe-nl-ams1.
PAYLOAD_STORE = os.getenv(
    "LAWGRAPH_PAYLOAD_STORE", "file://~/.local/share/lawgraph/payloads"
)
# Where the API keeps the counts of the terms searched (``core/search_stats.py``).
SEARCH_STATS_DIR = Path(
    os.getenv("LAWGRAPH_SEARCH_STATS_DIR", "~/.local/share/lawgraph/search-stats")
).expanduser()
S3_ENDPOINT = os.getenv("LAWGRAPH_S3_ENDPOINT") or None
S3_REGION = os.getenv("LAWGRAPH_S3_REGION") or None
S3_ACCESS_KEY = os.getenv("LAWGRAPH_S3_ACCESS_KEY") or None
S3_SECRET_KEY = os.getenv("LAWGRAPH_S3_SECRET_KEY") or None

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
RIJKSOVERHEID_BASE = os.getenv("RIJKSOVERHEID_BASE", "https://www.rijksoverheid.nl")
# The website of the Eerste Kamer: its list of votes on bills and of rejected bills.
EERSTEKAMER_SITE = os.getenv("EERSTEKAMER_SITE", "https://www.eerstekamer.nl")
# How the API names the Eerste Kamer as the source of what it takes over from its website
# (its terms allow reuse with the source and the day it was taken over).
EK_ATTRIBUTION = os.getenv(
    "EK_ATTRIBUTION", "Eerste Kamer der Staten-Generaal, www.eerstekamer.nl"
)
TOOI_BASE = os.getenv("TOOI_BASE", "https://identifier.overheid.nl")

# ── Pipelines ─────────────────────────────────────────────────────────────────

BWB_IDS = _env_list("BWB_IDS")


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
# The longest one request to the API may read the database, in milliseconds: every
# statement of it gets what is left (a request of eight counts lasts no eight ceilings).
API_REQUEST_TIMEOUT_MS = _env_positive_int("LAWGRAPH_API_REQUEST_TIMEOUT_MS", 30_000)
# The API computes the answers every visitor asks (facets of the unfiltered lists, the
# statistics, the heat) at its start and after every data change, in the background.
API_WARM_UP = os.getenv("LAWGRAPH_API_WARM_UP", "true").strip().lower() != "false"
# The heat of the whole graph (``/api/nodes/heat`` without ``ids``), which reads every
# edge; ``false`` answers it 503 at once (the heat of named nodes stays).
API_HEAT = os.getenv("LAWGRAPH_API_HEAT", "true").strip().lower() != "false"
API_RATE_LIMIT_CALLS = int(os.getenv("LAWGRAPH_RATE_LIMIT_CALLS", "200"))
API_RATE_LIMIT_PERIOD = float(os.getenv("LAWGRAPH_RATE_LIMIT_PERIOD", "60"))
API_TRUSTED_PROXIES = frozenset(_env_list("LAWGRAPH_TRUSTED_PROXIES"))
API_CACHE_TTL = float(os.getenv("LAWGRAPH_CACHE_TTL", "60"))
API_CACHE_MAXSIZE = int(os.getenv("LAWGRAPH_CACHE_MAXSIZE", "512"))
# The front end (Concordans) the Atom feed links its pages to, without a trailing slash.
SITE_URL = os.getenv("LAWGRAPH_SITE_URL", "http://localhost:5173").rstrip("/")

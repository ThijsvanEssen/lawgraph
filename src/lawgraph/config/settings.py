"""Runtime configuration: every value that comes from the environment.

Importing this module loads ``.env`` (searched from the working directory upwards), so any
code that reads a setting sees it. Variables already set in the process environment win over
``.env``. No other module reads ``os.environ``.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from pathlib import Path
from urllib.parse import quote

from dotenv import find_dotenv, load_dotenv

load_dotenv(find_dotenv(usecwd=True))

# Every variable is named ``LAWGRAPH_<SETTING>`` after the setting it sets. These were read
# under another name before; one still set under it fails the start, instead of leaving the
# setting at its default without a word.
_RENAMED = {"BWB_IDS": "LAWGRAPH_BWB_IDS", "EK_ATTRIBUTION": "LAWGRAPH_EK_ATTRIBUTION"}
for _old, _new in _RENAMED.items():
    if _old in os.environ:
        raise ValueError(f"{_old} is now called {_new}; rename it in the environment")

# Every reader below takes an unset or empty variable as its default and fails on any value
# it cannot read, with the name of the variable: a typo never becomes a default.

_TRUE = frozenset({"1", "true", "yes", "on"})
_FALSE = frozenset({"0", "false", "no", "off"})


def _raw(name: str) -> str | None:
    return os.getenv(name, "").strip() or None


def _invalid(name: str, raw: str, expected: str) -> ValueError:
    return ValueError(f"{name}={raw!r}: expected {expected}")


def _flag(name: str, default: bool) -> bool:
    raw = _raw(name)
    if raw is None:
        return default
    if raw.lower() in _TRUE:
        return True
    if raw.lower() in _FALSE:
        return False
    raise _invalid(name, raw, "true/false (1/0, yes/no, on/off)")


def _int(name: str, default: int) -> int:
    """A count, a size or a ceiling: never 0, which would turn it off."""
    raw = _raw(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        value = 0
    if value <= 0:
        raise _invalid(name, raw, "a positive whole number")
    return value


def _float(name: str, default: float) -> float:
    raw = _raw(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        raise _invalid(name, raw, "a number") from None


def _choice(name: str, default: str, choices: Sequence[str]) -> str:
    raw = _raw(name)
    if raw is None:
        return default
    for choice in choices:
        if raw.lower() == choice.lower():
            return choice
    raise _invalid(name, raw, "one of " + ", ".join(choices))


def _list(name: str, default: str = "") -> list[str]:
    return [
        item.strip() for item in os.getenv(name, default).split(",") if item.strip()
    ]


# ── Logging ───────────────────────────────────────────────────────────────────

LOG_LEVEL = _choice("LAWGRAPH_LOG_LEVEL", "INFO", tuple(logging.getLevelNamesMapping()))
# ``json``: one JSON object per line.
LOG_FORMAT = _choice("LAWGRAPH_LOG_FORMAT", "text", ("text", "json"))
NO_COLOR = os.getenv("NO_COLOR") is not None
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
DB_POOL_SIZE = _int("LAWGRAPH_DB_POOL_SIZE", 8)
# Connections of one process for what the API computes in the background (its warm-up and
# the answers it keeps per data version), apart from the ones above: a slow computation
# never keeps a request waiting for a connection. Opened when first needed. One for each
# computation of ``version_cache`` (its ``WORKERS``, 3) and one for the warm-up.
DB_BACKGROUND_POOL_SIZE = _int("LAWGRAPH_DB_BACKGROUND_POOL_SIZE", 4)
# A database whose strings sort by another collation than the schema's ICU collation is
# refused; this names the one let through anyway, for the dump and restore that replaces it
# (``libc en_US.utf8``, as the refusal names it).
ALLOW_COLLATION = os.getenv("LAWGRAPH_ALLOW_COLLATION", "").strip()
# The longest a statement that writes may run (``statement_timeout``, db/store.py), in
# milliseconds: a ceiling that is never off. A build on a slow disk raises it.
WRITE_TIMEOUT_MS = _int("LAWGRAPH_WRITE_TIMEOUT_MS", 600_000)
# The longest one statement that reads may run, in milliseconds (a FETCH of a streamed
# read is a statement of its own): a ceiling for a plan that never ends, never off.
READ_TIMEOUT_MS = _int("LAWGRAPH_READ_TIMEOUT_MS", 10_800_000)
# Every this many minutes a running step logs how long it runs and the statements of its
# process that have run for over a minute (``pipelines/watchdog.py``).
WATCHDOG_MINUTES = _int("LAWGRAPH_WATCHDOG_MINUTES", 10)

# ── ArangoDB connection ───────────────────────────────────────────────────────

ARANGO_URL = os.getenv("ARANGO_URL", "http://localhost:8529")
ARANGO_DB_NAME = os.getenv("ARANGO_DB_NAME", "lawgraph")
ARANGO_USER = os.getenv("ARANGO_USER", "root")
ARANGO_PASSWORD = os.getenv("ARANGO_PASSWORD", "")
# Slightly above the 600 s a writing query may take (db/store.py), so the server times out
# before the client.
ARANGO_REQUEST_TIMEOUT = 620

# The database shares the server's data volume with its WAL and whatever else the server
# keeps there. `lawgraph check` fails from this size on, while the volume has room to act.
DB_SIZE_ALERT_GIB = _float("LAWGRAPH_DB_SIZE_ALERT_GIB", 70)

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
# Where ``lawgraph sitemaps`` writes the sitemaps of Concordans, which Caddy serves.
SITEMAP_DIR = Path(
    os.getenv("LAWGRAPH_SITEMAP_DIR", "~/.local/share/lawgraph/sitemaps")
).expanduser()
S3_ENDPOINT = os.getenv("LAWGRAPH_S3_ENDPOINT") or None
S3_REGION = os.getenv("LAWGRAPH_S3_REGION") or None
S3_ACCESS_KEY = os.getenv("LAWGRAPH_S3_ACCESS_KEY") or None
S3_SECRET_KEY = os.getenv("LAWGRAPH_S3_SECRET_KEY") or None

# ── External sources ──────────────────────────────────────────────────────────

# How the API names the Eerste Kamer as the source of what it takes over from its website
# (its terms allow reuse with the source and the day it was taken over).
EK_ATTRIBUTION = os.getenv(
    "LAWGRAPH_EK_ATTRIBUTION", "Eerste Kamer der Staten-Generaal, www.eerstekamer.nl"
)

# ── Pipelines ─────────────────────────────────────────────────────────────────

BWB_IDS = _list("LAWGRAPH_BWB_IDS")


def skip_step(phase: str, pipeline_name: str) -> bool:
    """True when ``LAWGRAPH_<PHASE>_SKIP_<NAME>=true`` leaves a pipeline out of ``<phase> all``."""
    return _flag(skip_variable(phase, pipeline_name), False)


def skip_variable(phase: str, pipeline_name: str) -> str:
    """``LAWGRAPH_NORMALIZE_SKIP_TK_DOSSIERS`` for ``normalize tk-dossiers``."""
    return f"LAWGRAPH_{phase.upper()}_SKIP_{pipeline_name.upper().replace('-', '_')}"


def confidence_override(pattern_name: str, default: float) -> float:
    """Confidence of one detection pattern: ``LAWGRAPH_CONFIDENCE_<PATTERN>`` or *default*."""
    return _float(f"LAWGRAPH_CONFIDENCE_{pattern_name.upper()}", default)


# ── API ───────────────────────────────────────────────────────────────────────

API_HOST = os.getenv("LAWGRAPH_API_HOST", "127.0.0.1")
API_PORT = _int("LAWGRAPH_API_PORT", 8000)
ALLOWED_ORIGINS = _list(
    "LAWGRAPH_ALLOWED_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173,http://localhost:5174,http://127.0.0.1:5174",
)
# The longest one request to the API may read the database, in milliseconds: every
# statement of it gets what is left (a request of eight counts lasts no eight ceilings).
API_REQUEST_TIMEOUT_MS = _int("LAWGRAPH_API_REQUEST_TIMEOUT_MS", 30_000)
# The API computes the answers every visitor asks (facets of the unfiltered lists, the
# statistics, the heat) at its start and after every data change, in the background.
API_WARM_UP = _flag("LAWGRAPH_API_WARM_UP", True)
# At least this many minutes between the starts of two warm-ups after a data change (0: none):
# a poll that writes every half hour does not keep the database warming. Between them the API
# answers from what it kept of the data before.
WARM_UP_MIN_INTERVAL = _float("LAWGRAPH_WARM_UP_MIN_INTERVAL", 0)
RATE_LIMIT_CALLS = _int("LAWGRAPH_RATE_LIMIT_CALLS", 200)
RATE_LIMIT_PERIOD = _float("LAWGRAPH_RATE_LIMIT_PERIOD", 60)
TRUSTED_PROXIES = frozenset(_list("LAWGRAPH_TRUSTED_PROXIES"))
# The front end (Concordans) the Atom feed links its pages to, without a trailing slash.
SITE_URL = os.getenv("LAWGRAPH_SITE_URL", "http://localhost:5173").rstrip("/")
# The built shell of the front end (``index.html`` of its build) the server HTML of a page
# is made from (``api/routes/render.py``); ``spa-routes.json`` next to it lists its pages.
SPA_INDEX = os.getenv(
    "LAWGRAPH_SPA_INDEX", "/srv/lawgraph/concordans/current/index.html"
)

"""Every host the clients ask: where it is, how far apart requests to it go, and the lane of
``retrieve all`` that talks to it.

The pacer (``clients/pacing.py``) keeps requests to one host ``min_interval`` seconds apart
at least; a host that answers HTTP 429 or 503 makes the interval grow, and it shrinks back
to this value while requests succeed. ``retrieve all`` runs the pipelines of one lane one
after the other, so no host gets two request streams; a lane can hold more than one host.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

# What every request names itself as.
USER_AGENT = "Concordans (https://github.com/ThijsvanEssen/lawgraph)"

# Seconds between two requests to a host that asks for nothing else.
DEFAULT_MIN_INTERVAL = 0.2


@dataclass(frozen=True)
class Host:
    base_url: str  # with a trailing slash
    lane: str
    min_interval: float = DEFAULT_MIN_INTERVAL

    @property
    def name(self) -> str:
        return urlsplit(self.base_url).hostname or ""


TWEEDE_KAMER = Host(
    "https://gegevensmagazijn.tweedekamer.nl/OData/v4/2.0/", "tweede_kamer", 0.1
)
# Rechtspraak allows "niet meer dan 10 requests per seconde" and asks to mind the others.
RECHTSPRAAK = Host("https://data.rechtspraak.nl/", "rechtspraak", 0.125)
# The CELLAR of the Publications Office: its SPARQL endpoint and the texts of EU acts.
CELLAR = Host("https://publications.europa.eu/", "eurlex", 0.3)
# The SRU of the BWB, and the repository its records point the toestanden and WTIs to.
BWB_SEARCH = Host("https://zoekservice.overheid.nl/", "bwb", 0.1)
BWB_REPOSITORY = Host(
    "https://repository.officiele-overheidspublicaties.nl/", "bwb", 0.1
)
# The SRU and the official publications of KOOP. Measured on 2026-09-20: it throttles from
# about 5 requests per second sustained (a bucket of about 20).
KOOP_REPOSITORY = Host("https://repository.overheid.nl/", "koop_repository", 0.5)
HUDOC = Host("https://hudoc.echr.coe.int/", "echr", 0.5)
# Websites, a page at a time with a pause, read seldom: 106 pages of votes of the Eerste
# Kamer, 33 cabinet pages, six pages of the Kiesraad's databank.
EERSTEKAMER_SITE = Host("https://www.eerstekamer.nl/", "eerstekamer_site", 2.0)
RIJKSOVERHEID = Host("https://www.rijksoverheid.nl/", "rijksoverheid", 2.0)
KIESRAAD = Host("https://www.verkiezingsuitslagen.nl/", "kiesraad", 2.0)
TOOI = Host("https://identifier.overheid.nl/", "tooi")

HOSTS = (
    TWEEDE_KAMER,
    RECHTSPRAAK,
    CELLAR,
    BWB_SEARCH,
    BWB_REPOSITORY,
    KOOP_REPOSITORY,
    HUDOC,
    EERSTEKAMER_SITE,
    RIJKSOVERHEID,
    KIESRAAD,
    TOOI,
)

# The endpoints that are not the base of their host.
BWB_SRU = f"{BWB_SEARCH.base_url}sru/Search"
KOOP_SRU = f"{KOOP_REPOSITORY.base_url}sru"
CELLAR_SPARQL = f"{CELLAR.base_url}webapi/rdf/sparql"
TK_DOCUMENT_RESOURCE_URL_TEMPLATE = (
    f"{TWEEDE_KAMER.base_url}Document({{external_id}})/resource"
)


def min_interval(host_name: str) -> float:
    """The interval of the host *host_name* (``repository.overheid.nl``); the default for
    a host that is not in the table."""
    return next(
        (host.min_interval for host in HOSTS if host.name == host_name),
        DEFAULT_MIN_INTERVAL,
    )

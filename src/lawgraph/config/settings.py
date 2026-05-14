"""LawGraph runtime configuration — single source of truth for all constants."""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def _env_list(name: str, default: tuple[str, ...]) -> list[str]:
    raw_value = os.getenv(name)
    if raw_value:
        return [s.strip() for s in raw_value.split(",") if s.strip()]
    return list(default)


# ── Collections ───────────────────────────────────────────────────────────────

DEFAULT_DOCUMENT_COLLECTIONS: tuple[str, ...] = (
    "instruments",
    "instrument_articles",
    "instrument_versions",
    "instrument_article_versions",
    "procedures",
    "publications",
    "judgments",
    "topics",
    "raw_sources",
    # Parliamentary dossier entities (spec §2.1)
    "kamerstukdossiers",
    "activiteiten",
    "stemmingen",
    "toezeggingen",
    "commissies",
    "leden",
    "fracties",
    # Immutable audit trail for edge-status flips (§ observability)
    "edge_status_log",
    # User watch-list (persisted server-side, keyed by UUID)
    "watches",
)

DOCUMENT_COLLECTIONS: list[str] = _env_list(
    "LAWGRAPH_DOCUMENT_COLLECTIONS", DEFAULT_DOCUMENT_COLLECTIONS
)

# Single unified edge collection (replaces the old edges_strict + edges_semantic split).
COLLECTION_EDGES = os.getenv("LAWGRAPH_EDGE_COLLECTION", "edges")

# ── ArangoDB connection ───────────────────────────────────────────────────────

DEFAULT_ARANGO_URL = "http://localhost:8529"
DEFAULT_ARANGO_DB_NAME = "lawgraph"
DEFAULT_ARANGO_USER = "root"
DEFAULT_ARANGO_PASSWORD = ""

ARANGO_URL = os.getenv("ARANGO_URL", DEFAULT_ARANGO_URL)
ARANGO_DB_NAME = os.getenv("ARANGO_DB_NAME", DEFAULT_ARANGO_DB_NAME)
ARANGO_USER = os.getenv("ARANGO_USER", DEFAULT_ARANGO_USER)
ARANGO_PASSWORD = os.getenv("ARANGO_PASSWORD", DEFAULT_ARANGO_PASSWORD)

# ── External API base URLs ────────────────────────────────────────────────────

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

DEFAULT_EURLEX_SPARQL_ENDPOINT = "https://publications.europa.eu/webapi/rdf/sparql"
EURLEX_SPARQL_ENDPOINT = os.getenv(
    "EURLEX_SPARQL_ENDPOINT", DEFAULT_EURLEX_SPARQL_ENDPOINT
)

DEFAULT_STAATSBLAD_SRU_ENDPOINT = "https://sru.officielebekendmakingen.nl/sru/Search"
STAATSBLAD_SRU_ENDPOINT = os.getenv(
    "STAATSBLAD_SRU_ENDPOINT", DEFAULT_STAATSBLAD_SRU_ENDPOINT
)
DEFAULT_STAATSBLAD_REPO_BASE = "https://repository.overheid.nl"
STAATSBLAD_REPO_BASE = os.getenv("STAATSBLAD_REPO_BASE", DEFAULT_STAATSBLAD_REPO_BASE)

DEFAULT_STAATSCOURANT_SRU_ENDPOINT = "https://sru.officielebekendmakingen.nl/sru/Search"
STAATSCOURANT_SRU_ENDPOINT = os.getenv(
    "STAATSCOURANT_SRU_ENDPOINT", DEFAULT_STAATSCOURANT_SRU_ENDPOINT
)

DEFAULT_EERSTEKAMER_BASE = "https://gegevensmagazijn.eerstekamer.nl/OData/v4/2.0/"
EERSTEKAMER_BASE_URL = os.getenv("EERSTEKAMER_BASE", DEFAULT_EERSTEKAMER_BASE)

DEFAULT_ECHR_HUDOC_BASE = "https://hudoc.echr.coe.int"
ECHR_HUDOC_BASE_URL = os.getenv("ECHR_HUDOC_BASE", DEFAULT_ECHR_HUDOC_BASE)

DEFAULT_VERDRAGENBANK_SPARQL = "https://linkeddata.overheid.nl/front/portal/sparql"
VERDRAGENBANK_SPARQL_ENDPOINT = os.getenv(
    "VERDRAGENBANK_SPARQL", DEFAULT_VERDRAGENBANK_SPARQL
)

# ── Source & raw-kind identifiers ─────────────────────────────────────────────

SOURCE_TK = "tk"
SOURCE_RECHTSPRAAK = "rechtspraak"
SOURCE_EURLEX = "eurlex"
SOURCE_BWB = "bwb"
SOURCE_STAATSBLAD = "staatsblad"
SOURCE_STAATSCOURANT = "staatscourant"
SOURCE_EERSTEKAMER = "eerstekamer"
SOURCE_ECHR = "echr"
SOURCE_VERDRAGENBANK = "verdragenbank"

RAW_KIND_TK_ZAAK = "tk-zaak"
RAW_KIND_TK_DOCUMENTVERSIE = "tk-documentversie"
RAW_KIND_TK_DOSSIER = "tk-dossier"
RAW_KIND_TK_ACTIVITEIT = "tk-activiteit"
RAW_KIND_TK_STEMMING = "tk-stemming"
RAW_KIND_TK_TOEZEGGING = "tk-toezegging"
RAW_KIND_TK_COMMISSIE = "tk-commissie"
RAW_KIND_TK_PERSOON = "tk-persoon"
RAW_KIND_TK_DOCUMENT = "tk-document"
RAW_KIND_TK_FRACTIE = "tk-fractie"
RAW_KIND_TK_FRACTIEZETELPERSOON = "tk-fractie-zetel-persoon"
RAW_KIND_RS_INDEX = "rs-index"
RAW_KIND_RS_CONTENT = "rs-content"
RAW_KIND_EU_CELEX = "eu-celex-html"
RAW_KIND_BWB_REGELING = "bwb-regeling-xml"
RAW_KIND_BWB_TOESTAND = "bwb-toestand-xml"
RAW_KIND_BWB_TOESTAND_ALL = "bwb-toestand-xml-all"
RAW_KIND_STB_AMVB = "stb-amvb-xml"
RAW_KIND_STCRT_REGELING = "stcrt-regeling-xml"
RAW_KIND_EK_STUK = "ek-stuk-json"
RAW_KIND_ECHR_JUDGMENT = "echr-judgment-json"
RAW_KIND_VERDRAG = "verdrag-json"

RAW_SOURCE_KINDS: dict[str, tuple[str, ...]] = {
    SOURCE_TK: (
        RAW_KIND_TK_ZAAK,
        RAW_KIND_TK_DOCUMENTVERSIE,
        RAW_KIND_TK_DOSSIER,
        RAW_KIND_TK_ACTIVITEIT,
        RAW_KIND_TK_STEMMING,
        RAW_KIND_TK_TOEZEGGING,
        RAW_KIND_TK_COMMISSIE,
        RAW_KIND_TK_PERSOON,
        RAW_KIND_TK_DOCUMENT,
        RAW_KIND_TK_FRACTIE,
        RAW_KIND_TK_FRACTIEZETELPERSOON,
    ),
    SOURCE_RECHTSPRAAK: (RAW_KIND_RS_INDEX, RAW_KIND_RS_CONTENT),
    SOURCE_EURLEX: (RAW_KIND_EU_CELEX,),
    SOURCE_BWB: (
        RAW_KIND_BWB_REGELING,
        RAW_KIND_BWB_TOESTAND,
        RAW_KIND_BWB_TOESTAND_ALL,
    ),
    SOURCE_STAATSBLAD: (RAW_KIND_STB_AMVB,),
    SOURCE_STAATSCOURANT: (RAW_KIND_STCRT_REGELING,),
    SOURCE_EERSTEKAMER: (RAW_KIND_EK_STUK,),
    SOURCE_ECHR: (RAW_KIND_ECHR_JUDGMENT,),
    SOURCE_VERDRAGENBANK: (RAW_KIND_VERDRAG,),
}

# ── Collection name constants ─────────────────────────────────────────────────

COLLECTION_INSTRUMENTS = "instruments"
COLLECTION_INSTRUMENT_ARTICLES = "instrument_articles"
COLLECTION_INSTRUMENT_VERSIONS = "instrument_versions"
COLLECTION_INSTRUMENT_ARTICLE_VERSIONS = "instrument_article_versions"
COLLECTION_PROCEDURES = "procedures"
COLLECTION_PUBLICATIONS = "publications"
COLLECTION_JUDGMENTS = "judgments"
COLLECTION_TOPICS = "topics"
COLLECTION_RAW_SOURCES = "raw_sources"
COLLECTION_KAMERSTUKDOSSIERS = "kamerstukdossiers"
COLLECTION_ACTIVITEITEN = "activiteiten"
COLLECTION_STEMMINGEN = "stemmingen"
COLLECTION_TOEZEGGINGEN = "toezeggingen"
COLLECTION_COMMISSIES = "commissies"
COLLECTION_LEDEN = "leden"
COLLECTION_FRACTIES = "fracties"
COLLECTION_EDGE_STATUS_LOG = "edge_status_log"
COLLECTION_WATCHES = "watches"

# ── Edge status values ────────────────────────────────────────────────────────
# Every edge carries a `status` field (top-level, indexed).
# Existing edges without the field are treated as EDGE_STATUS_CANONIEK in queries.

EDGE_STATUS_CANONIEK = "canoniek"  # current law
EDGE_STATUS_VOORGESTELD = "voorgesteld"  # pending mutation from an open dossier
EDGE_STATUS_VERLOPEN = "verlopen"  # no longer in force
EDGE_STATUS_VERWORPEN = "verworpen"  # rejected by stemming

# ── Relation type constants ───────────────────────────────────────────────────
# Single source of truth for relation strings.
# Do NOT define relation strings anywhere else in the codebase.

# Structural — written by normalize pipelines, fully deterministic.
RELATION_PART_OF_INSTRUMENT = "PART_OF_INSTRUMENT"  # article → instrument
RELATION_PART_OF_PROCEDURE = "PART_OF_PROCEDURE"  # publication → procedure (zaak)
RELATION_DEEL_VAN_DOSSIER = "DEEL_VAN_DOSSIER"  # zaak/pub/activiteit → kamerstukdossier
RELATION_DISCUSSES = "DISCUSSES"  # procedure → instrument

# Parliamentary structural — written by dossier normalize pipeline.
RELATION_RAAKT = "RAAKT"  # kamerstukdossier → instrument (dossier touches this law)
RELATION_WIJZIGT = (
    "WIJZIGT"  # document → article (proposes a change); status=voorgesteld
)
RELATION_INTRODUCEERT = "INTRODUCEERT"  # document → article (introduces new article)
RELATION_TREKT_IN = "TREKT_IN"  # document → article (proposes repeal)
RELATION_AMENDEERT = "AMENDEERT"  # amendement → document (amends a wetsvoorstel)
RELATION_LICHT_TOE = "LICHT_TOE"  # mvt → article (explains legislative intent)
RELATION_BESLUIT = "BESLUIT"  # stemming → document (finalizes or rejects)
RELATION_BETREFT = "BETREFT"  # toezegging → article (optional specific article)
RELATION_BEHANDELD_DOOR = "BEHANDELD_DOOR"  # activiteit → commissie
RELATION_LID_VAN = "LID_VAN"  # lid → commissie
RELATION_GEDAAN_IN = "GEDAAN_IN"  # toezegging → activiteit
RELATION_AUTEUR_VAN = "AUTEUR_VAN"  # lid → document
RELATION_GESTEMD_IN = "GESTEMD_IN"  # stemming → activiteit
RELATION_LID_VAN_FRACTIE = "LID_VAN_FRACTIE"  # lid → fractie (party membership)
RELATION_STEMT = "STEMT"  # fractie → stemming (group vote, with meta.stem)

# Semantic — written by semantic pipelines, confidence-weighted.
RELATION_REFERS_TO_ARTICLE = os.getenv(
    "LAWGRAPH_RELATION_REFERS_TO_ARTICLE", "REFERS_TO_ARTICLE"
)
RELATION_EXPLAINS_ARTICLE = os.getenv(
    "LAWGRAPH_RELATION_EXPLAINS_ARTICLE", "EXPLAINS_ARTICLE"
)
RELATION_CITES_ARTICLE = os.getenv("LAWGRAPH_RELATION_CITES_ARTICLE", "CITES_ARTICLE")
RELATION_MENTIONS_ARTICLE = os.getenv(
    "LAWGRAPH_RELATION_MENTIONS_ARTICLE", "MENTIONS_ARTICLE"
)
RELATION_CITES_JUDGMENT = os.getenv(
    "LAWGRAPH_RELATION_CITES_JUDGMENT", "CITES_JUDGMENT"
)
RELATION_MENTIONS_INSTRUMENT = os.getenv(
    "LAWGRAPH_RELATION_MENTIONS_INSTRUMENT", "MENTIONS_INSTRUMENT"
)
RELATION_AMENDS_INSTRUMENT = os.getenv(
    "LAWGRAPH_RELATION_AMENDS_INSTRUMENT", "AMENDS_INSTRUMENT"
)
RELATION_IMPLEMENTS_DIRECTIVE = os.getenv(
    "LAWGRAPH_RELATION_IMPLEMENTS_DIRECTIVE", "IMPLEMENTS_DIRECTIVE"
)
RELATION_RELATED_TOPIC = "RELATED_TOPIC"
RELATION_EXPLAINS_INSTRUMENT = (
    "EXPLAINS_INSTRUMENT"  # publication → instrument (NvT, explanatory)
)
RELATION_DELEGATED_BY = (
    "DELEGATED_BY"  # instrument (AMvB) → article (legal delegation basis)
)
RELATION_RESULTED_IN = "RESULTED_IN"  # kamerstukdossier → instrument (enacted law)
RELATION_SUPERSEDES = (
    "SUPERSEDES"  # newer instrument_version → older instrument_version
)
RELATION_VERSION_OF = "VERSION_OF"  # instrument_version → instrument
RELATION_PART_OF_VERSION = "PART_OF_VERSION"  # article_version → instrument_version
RELATION_CAUSED_VERSION = (
    "CAUSED_VERSION"  # publication → instrument_article_version (legislative cause)
)


# ── Semantic confidence overrides ─────────────────────────────────────────────
# Env-var-driven per-pattern floor adjustments.
# Format: dict[pattern_name, float] where pattern_name matches the detector's
# internal pattern identifier. Detectors read this via get_confidence_override().


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
        return default

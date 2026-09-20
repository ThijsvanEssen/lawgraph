"""Names used across LawGraph: collections, relation types, source ids, raw kinds."""

from __future__ import annotations

from types import MappingProxyType

# ── Collection name constants ─────────────────────────────────────────────────

COLLECTION_INSTRUMENTS = "instruments"
COLLECTION_ARTICLES = "articles"
COLLECTION_INSTRUMENT_VERSIONS = "instrument_versions"
COLLECTION_ARTICLE_VERSIONS = "article_versions"
COLLECTION_CASES = "cases"
COLLECTION_DOCUMENTS = "documents"
COLLECTION_JUDGMENTS = "judgments"
COLLECTION_DOSSIERS = "dossiers"
COLLECTION_ACTIVITIES = "activities"
COLLECTION_DECISIONS = "decisions"
COLLECTION_COMMITMENTS = "commitments"
COLLECTION_COMMITTEES = "committees"
COLLECTION_MEMBERS = "members"
COLLECTION_FACTIONS = "factions"
COLLECTION_EDGE_STATUS_LOG = "edge_status_log"
COLLECTION_TOPICS = "topics"
COLLECTION_RAW_SOURCES = "raw_sources"
COLLECTION_WATCHES = "watches"
COLLECTION_ANNEXES = "annexes"
COLLECTION_EDGES = "edges"

DOCUMENT_COLLECTIONS: tuple[str, ...] = (
    COLLECTION_INSTRUMENTS,
    COLLECTION_ARTICLES,
    COLLECTION_INSTRUMENT_VERSIONS,
    COLLECTION_ARTICLE_VERSIONS,
    COLLECTION_CASES,
    COLLECTION_DOCUMENTS,
    COLLECTION_JUDGMENTS,
    COLLECTION_TOPICS,
    COLLECTION_RAW_SOURCES,
    COLLECTION_DOSSIERS,
    COLLECTION_ACTIVITIES,
    COLLECTION_DECISIONS,
    COLLECTION_COMMITMENTS,
    COLLECTION_COMMITTEES,
    COLLECTION_MEMBERS,
    COLLECTION_FACTIONS,
    COLLECTION_EDGE_STATUS_LOG,
    COLLECTION_WATCHES,
    COLLECTION_ANNEXES,
)

# ── Edge status values ────────────────────────────────────────────────────────

EDGE_STATUS_CANONIEK = "canoniek"  # current law
EDGE_STATUS_VOORGESTELD = "voorgesteld"  # pending mutation from an open dossier

# ── Relation type constants ───────────────────────────────────────────────────
# One constant per relation in ``core.relations.RELATIONS``; the names and their
# meaning live in that catalogue. Relation strings are written nowhere else.

RELATION_PART_OF = "PART_OF"
RELATION_VERSION_OF = "VERSION_OF"
RELATION_AMENDS = "AMENDS"
RELATION_INTRODUCES = "INTRODUCES"
RELATION_REPEALS = "REPEALS"
RELATION_BASED_ON = "BASED_ON"
RELATION_IMPLEMENTS = "IMPLEMENTS"
RELATION_LEGISLATED_IN = "LEGISLATED_IN"
RELATION_REFERS_TO = "REFERS_TO"
RELATION_EXPLAINS = "EXPLAINS"
RELATION_APPEAL_OF = "APPEAL_OF"
RELATION_SCOPED_BY = "SCOPED_BY"
RELATION_ABOUT = "ABOUT"
RELATION_LED_BY = "LED_BY"
RELATION_MADE_IN = "MADE_IN"
RELATION_MEMBER_OF = "MEMBER_OF"
RELATION_AUTHORED = "AUTHORED"
RELATION_VOTED = "VOTED"

# ── Semantic relationship types ───────────────────────────────────────────────
# Curated semantic layer stored on edges as `semantic_type`. Orthogonal to
# `relation` (which says *that* two nodes are linked); semantic_type says
# *what the link legally means*. Nullable — most edges remain unclassified.

SEMANTIC_TYPE_CONDITIONAL_REQUIREMENT = "conditional_requirement"
SEMANTIC_TYPE_SCOPE_LIMITATION = "scope_limitation"
SEMANTIC_TYPE_PREREQUISITE_PROCEDURE = "prerequisite_procedure"
SEMANTIC_TYPE_DEFINITIONAL_REFERENCE = "definitional_reference"
SEMANTIC_TYPE_LIMITING_EXCEPTION = "limiting_exception"
SEMANTIC_TYPE_CROSS_REFERENCE = "cross_reference"
SEMANTIC_TYPE_DELEGATED_DISCRETION = "delegated_discretion"

SEMANTIC_RELATIONSHIP_TYPES: frozenset[str] = frozenset(
    {
        SEMANTIC_TYPE_CONDITIONAL_REQUIREMENT,
        SEMANTIC_TYPE_SCOPE_LIMITATION,
        SEMANTIC_TYPE_PREREQUISITE_PROCEDURE,
        SEMANTIC_TYPE_DEFINITIONAL_REFERENCE,
        SEMANTIC_TYPE_LIMITING_EXCEPTION,
        SEMANTIC_TYPE_CROSS_REFERENCE,
        SEMANTIC_TYPE_DELEGATED_DISCRETION,
    }
)

# Provenance of a semantic_type assignment, stored on edges as `semantic_source`.
# (Distinct from the edge-level `source` field, which names the pipeline that
# created the edge itself.)
SEMANTIC_SOURCE_STRUCTURED = "structured"  # deterministic text-pattern extraction
SEMANTIC_SOURCE_EXPERT = "expert"  # validated by a legal expert
SEMANTIC_SOURCE_COMMUNITY = "community"  # community-proposed tag
SEMANTIC_SOURCE_LLM = "llm"  # future: LLM-assisted classification

SEMANTIC_SOURCES: frozenset[str] = frozenset(
    {
        SEMANTIC_SOURCE_STRUCTURED,
        SEMANTIC_SOURCE_EXPERT,
        SEMANTIC_SOURCE_COMMUNITY,
        SEMANTIC_SOURCE_LLM,
    }
)

# Scope of a SCOPED_BY link: fixed list vs. ministerially expandable.
SCOPE_TYPE_FIXED = "fixed"
SCOPE_TYPE_DISCRETIONARY = "discretionary"

# ── Source identifier constants ───────────────────────────────────────────────

SOURCE_TK = "tk"
SOURCE_RECHTSPRAAK = "rechtspraak"
SOURCE_EURLEX = "eurlex"
SOURCE_BWB = "bwb"

# BWB ``dcterms.type`` values that count as instruments: rules with a basis in a
# power laid down in law (statutes, AMvBs, KBs, ministerial regulations, ZBO/PBO
# regulations, policy rules, regulations, treaties, and the BES variants).
# Not included: "circulaire" — internal instructions without a legislative basis.
BWB_INSTRUMENT_TYPES: tuple[str, ...] = (
    "wet",
    "rijkswet",
    "AMvB",
    "rijksAMvB",
    "KB",
    "rijksKB",
    "ministeriele-regeling",
    "ministeriele-regeling-archiefselectielijst",
    "zbo",
    "pbo",
    "reglement",
    "beleidsregel",
    "verdrag",
    "wet-BES",
    "AMvB-BES",
    "ministeriele-regeling-BES",
    "beleidsregel-BES",
)
SOURCE_STAATSBLAD = "staatsblad"
SOURCE_STAATSCOURANT = "staatscourant"
SOURCE_ECHR = "echr"
SOURCE_VERDRAGENBANK = "verdragenbank"

# ── Raw source kind identifiers ───────────────────────────────────────────────

RAW_KIND_TK_ZAAK = "tk-zaak"
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
# The ``<algemene-informatie>`` element of a WTI file (official abbreviations), not the file.
RAW_KIND_BWB_WTI_GENERAL = "bwb-wti-algemene-informatie-xml"
RAW_KIND_STB_AMVB = "stb-amvb-xml"
RAW_KIND_STCRT_REGELING = "stcrt-regeling-xml"
RAW_KIND_ECHR_JUDGMENT = "echr-judgment-json"
RAW_KIND_VERDRAG = "verdrag-json"

RAW_SOURCE_KINDS: dict[str, tuple[str, ...]] = {
    SOURCE_TK: (
        RAW_KIND_TK_ZAAK,
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
        RAW_KIND_BWB_WTI_GENERAL,
    ),
    SOURCE_STAATSBLAD: (RAW_KIND_STB_AMVB,),
    SOURCE_STAATSCOURANT: (RAW_KIND_STCRT_REGELING,),
    SOURCE_ECHR: (RAW_KIND_ECHR_JUDGMENT,),
    SOURCE_VERDRAGENBANK: (RAW_KIND_VERDRAG,),
}

# ── Semantic pipeline limits ──────────────────────────────────────────────────

# Maximum characters of a document's text scanned for citations (200 KB).
MAX_SEMANTIC_TEXT_LENGTH = 200_000

# ── Party colors ──────────────────────────────────────────────────────────────
# Canonical brand colors for Dutch parliamentary parties.
# Keyed by the party abbreviation as it appears in fractie.abbreviation.
# GL-PvdA, GroenLinks, and GroenLinks-PvdA are all intentional duplicates:
# different API versions use different abbreviations for the same merged party.

PARTY_COLORS: MappingProxyType[str, str] = MappingProxyType(
    {
        "VVD": "#003082",
        "D66": "#1DB954",
        "PVV": "#002868",
        "CDA": "#399E48",
        "SP": "#EE1C25",
        "PvdA": "#E63325",
        "GroenLinks": "#46962B",
        "GL-PvdA": "#46962B",
        "GroenLinks-PvdA": "#46962B",
        "ChristenUnie": "#4F95D4",
        "Volt": "#592D82",
        "NSC": "#1B4F72",
        "BBB": "#9ECA3C",
        "JA21": "#CC0000",
        "SGP": "#FF6600",
        "FvD": "#8B0000",
        "FVD": "#8B0000",
        "DENK": "#39B54A",
        "BIJ1": "#FFCC00",
        "50PLUS": "#8B008B",
        "PvdD": "#4CAF50",
        "Groep Van Haga": "#002868",
        "Groep Markuszower": "#1F2A44",
        "Lid Keijzer": "#999999",
    }
)

# Longest title / display name stored on a node (longer source titles are truncated).
MAX_TITLE_CHARS = 200

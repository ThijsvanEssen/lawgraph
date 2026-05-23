"""Domain constants for LawGraph — collection names, relation types, source IDs, raw kinds.

These are compile-time string constants (never env-var derived).
Runtime configuration (database URL, credentials, external endpoints) lives in settings.py.
"""

from __future__ import annotations

from types import MappingProxyType

# ── BWB identifier prefix ─────────────────────────────────────────────────────

BWB_ID_PREFIX = "BWBR"

# ── Collection name constants ─────────────────────────────────────────────────

COLLECTION_INSTRUMENTS = "instruments"
COLLECTION_INSTRUMENT_ARTICLES = "instrument_articles"
COLLECTION_INSTRUMENT_VERSIONS = "instrument_versions"
COLLECTION_INSTRUMENT_ARTICLE_VERSIONS = "instrument_article_versions"
COLLECTION_PROCEDURES = "procedures"
COLLECTION_PUBLICATIONS = "publications"
COLLECTION_JUDGMENTS = "judgments"
COLLECTION_KAMERSTUKDOSSIERS = "kamerstukdossiers"
COLLECTION_ACTIVITEITEN = "activiteiten"
COLLECTION_STEMMINGEN = "stemmingen"
COLLECTION_TOEZEGGINGEN = "toezeggingen"
COLLECTION_COMMISSIES = "commissies"
COLLECTION_LEDEN = "leden"
COLLECTION_FRACTIES = "fracties"
COLLECTION_EDGE_STATUS_LOG = "edge_status_log"
COLLECTION_TOPICS = "topics"
COLLECTION_RAW_SOURCES = "raw_sources"
COLLECTION_WATCHES = "watches"

# ── Edge status values ────────────────────────────────────────────────────────

EDGE_STATUS_CANONIEK = "canoniek"  # current law
EDGE_STATUS_VOORGESTELD = "voorgesteld"  # pending mutation from an open dossier

# ── Relation type constants ───────────────────────────────────────────────────
# Single source of truth for relation strings. Do NOT define these anywhere else.

# Structural — written by normalize pipelines, fully deterministic.
RELATION_PART_OF_INSTRUMENT = "PART_OF_INSTRUMENT"  # article → instrument
RELATION_PART_OF_PROCEDURE = "PART_OF_PROCEDURE"  # publication → procedure (zaak)
RELATION_DEEL_VAN_DOSSIER = "DEEL_VAN_DOSSIER"  # zaak/pub/activiteit → kamerstukdossier
RELATION_DISCUSSES = "DISCUSSES"  # procedure → instrument

# Parliamentary structural — written by dossier normalize pipeline.
RELATION_RAAKT = "RAAKT"  # kamerstukdossier → instrument
RELATION_WIJZIGT = "WIJZIGT"  # document → article (proposes change); status=voorgesteld
RELATION_INTRODUCEERT = "INTRODUCEERT"  # document → article (introduces new article)
RELATION_TREKT_IN = "TREKT_IN"  # document → article (proposes repeal)
RELATION_LICHT_TOE = "LICHT_TOE"  # mvt → article (explains legislative intent)
RELATION_BESLUIT = "BESLUIT"  # stemming → document (finalizes or rejects)
RELATION_BEHANDELD_DOOR = "BEHANDELD_DOOR"  # activiteit → commissie
RELATION_LID_VAN = "LID_VAN"  # lid → commissie
RELATION_GEDAAN_IN = "GEDAAN_IN"  # toezegging → activiteit
RELATION_AUTEUR_VAN = "AUTEUR_VAN"  # lid → document
RELATION_LID_VAN_FRACTIE = "LID_VAN_FRACTIE"  # lid → fractie (party membership)
RELATION_STEMT = "STEMT"  # fractie → stemming (group vote, with meta.stem)

# Semantic — written by semantic pipelines, confidence-weighted.
RELATION_REFERS_TO_ARTICLE = "REFERS_TO_ARTICLE"
RELATION_EXPLAINS_ARTICLE = "EXPLAINS_ARTICLE"
RELATION_CITES_ARTICLE = "CITES_ARTICLE"
RELATION_MENTIONS_ARTICLE = "MENTIONS_ARTICLE"
RELATION_CITES_JUDGMENT = "CITES_JUDGMENT"
RELATION_MENTIONS_INSTRUMENT = "MENTIONS_INSTRUMENT"
RELATION_AMENDS_INSTRUMENT = "AMENDS_INSTRUMENT"
RELATION_IMPLEMENTS_DIRECTIVE = "IMPLEMENTS_DIRECTIVE"
RELATION_EXPLAINS_INSTRUMENT = "EXPLAINS_INSTRUMENT"  # publication → instrument (NvT)
RELATION_DELEGATED_BY = "DELEGATED_BY"  # instrument (AMvB) → article (delegation basis)
RELATION_RESULTED_IN = "RESULTED_IN"  # kamerstukdossier → instrument (enacted law)
RELATION_SUPERSEDES = "SUPERSEDES"  # newer version → older version
RELATION_VERSION_OF = "VERSION_OF"  # instrument_version → instrument
RELATION_PART_OF_VERSION = "PART_OF_VERSION"  # article_version → instrument_version
RELATION_CAUSED_VERSION = "CAUSED_VERSION"  # publication → instrument_article_version
RELATION_APPEAL_OF = "APPEAL_OF"  # hoger beroep/cassatie → prior judgment

# ── Source identifier constants ───────────────────────────────────────────────

SOURCE_TK = "tk"
SOURCE_RECHTSPRAAK = "rechtspraak"
SOURCE_EURLEX = "eurlex"
SOURCE_BWB = "bwb"
SOURCE_STAATSBLAD = "staatsblad"
SOURCE_STAATSCOURANT = "staatscourant"
SOURCE_EERSTEKAMER = "eerstekamer"
SOURCE_ECHR = "echr"
SOURCE_VERDRAGENBANK = "verdragenbank"

# ── Raw source kind identifiers ───────────────────────────────────────────────

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

# ── Party colors ──────────────────────────────────────────────────────────────
# Canonical brand colors for Dutch parliamentary parties.
# Keyed by the party abbreviation as it appears in fractie.afkorting.
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

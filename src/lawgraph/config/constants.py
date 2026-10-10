"""Names used across LawGraph: collections, relation types, source ids, raw kinds."""

from __future__ import annotations

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
COLLECTION_CABINETS = "cabinets"
COLLECTION_RAW_SOURCES = "raw_sources"
COLLECTION_ANNEXES = "annexes"
COLLECTION_PIPELINE_STATE = "pipeline_state"  # until when each phase is complete
COLLECTION_EDGES = "edges"

DOCUMENT_COLLECTIONS: tuple[str, ...] = (
    COLLECTION_INSTRUMENTS,
    COLLECTION_ARTICLES,
    COLLECTION_INSTRUMENT_VERSIONS,
    COLLECTION_ARTICLE_VERSIONS,
    COLLECTION_CASES,
    COLLECTION_DOCUMENTS,
    COLLECTION_JUDGMENTS,
    COLLECTION_RAW_SOURCES,
    COLLECTION_DOSSIERS,
    COLLECTION_ACTIVITIES,
    COLLECTION_DECISIONS,
    COLLECTION_COMMITMENTS,
    COLLECTION_COMMITTEES,
    COLLECTION_MEMBERS,
    COLLECTION_FACTIONS,
    COLLECTION_CABINETS,
    COLLECTION_ANNEXES,
    COLLECTION_PIPELINE_STATE,
)

# ── Search ────────────────────────────────────────────────────────────────────

# The analyzer of the words of a text in the search views, and of the words a query is
# split into. The texts are Dutch: a Dutch stemmer makes "uitspraken" find "uitspraak".
TEXT_ANALYZER = "text_nl"

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
RELATION_PUBLISHED_IN = "PUBLISHED_IN"
RELATION_REFERS_TO = "REFERS_TO"
RELATION_EXPLAINS = "EXPLAINS"
RELATION_APPEAL_OF = "APPEAL_OF"
RELATION_CONTINUES = "CONTINUES"
RELATION_REFERRED_BY = "REFERRED_BY"
RELATION_ADVISES_ON = "ADVISES_ON"
RELATION_ANSWERS = "ANSWERS"
RELATION_SAME_AS = "SAME_AS"
RELATION_SCOPED_BY = "SCOPED_BY"
RELATION_ABOUT = "ABOUT"
RELATION_LED_BY = "LED_BY"
RELATION_MADE_IN = "MADE_IN"
RELATION_MEMBER_OF = "MEMBER_OF"
RELATION_AUTHORED = "AUTHORED"
RELATION_VOTED = "VOTED"
RELATION_RELATED_TO = "RELATED_TO"
RELATION_REVISES = "REVISES"
RELATION_ACCOMPANIES = "ACCOMPANIES"
RELATION_SECOND_READING_OF = "SECOND_READING_OF"
RELATION_SERVED_IN = "SERVED_IN"

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
SOURCE_EERSTEKAMER = "eerstekamer"
SOURCE_VERDRAGENBANK = "verdragenbank"
SOURCE_RIJKSOVERHEID = "rijksoverheid"
SOURCE_TOOI = "tooi"
SOURCE_KIESRAAD = "kiesraad"
# The label of a member only Rijksoverheid knows: a bewindspersoon without a Tweede Kamer person.
LABEL_RIJKSOVERHEID = "Rijksoverheid"

# The chambers of the States General, as a document or decision carries them in its labels.
CHAMBER_TK = "TK"
CHAMBER_EK = "EK"

# A document is explanatory (an MvT, NvT, nota van toelichting) when its ``props.kind``
# contains this, in any case. AQL and ``core.documents.is_explanatory`` both use it.
EXPLANATORY_KIND_MARKER = "toelichting"

# The edge `source` of IMPLEMENTS (and of the REFERS_TO from a regulation to an EU act its
# text names without implementing it), with the basis of an IMPLEMENTS edge in its `meta`.
EDGE_SOURCE_BWB_IMPLEMENTS = "bwb-implements"
# The edge `source` of what `semantic verdragenbank` derives from the register of a treaty.
EDGE_SOURCE_VERDRAGENBANK = "verdragenbank"
IMPLEMENTS_BASIS_NIM = "national_implementing_measure"
IMPLEMENTS_BASIS_CONSIDERANS = "considerans"

# International instruments the graph has a name for: BWB treaties carry a BWBV id. The
# Convention of the ECHR is one of them: the treaty whose articles ECHR judgments apply.
BWB_TREATY_ID_PREFIX = "BWBV"
ECHR_CONVENTION_BWB_ID = "BWBV0001000"

# ── Raw source kind identifiers ───────────────────────────────────────────────

RAW_KIND_TK_ZAAK = "tk-zaak"
RAW_KIND_TK_DOSSIER = "tk-dossier"
RAW_KIND_TK_ACTIVITEIT = "tk-activiteit"
RAW_KIND_TK_STEMMING = "tk-stemming"
# A Besluit "Stemmen - ..." on the zaak of a bill, also one without votes (a hamerstuk).
RAW_KIND_TK_BESLUIT = "tk-besluit"
RAW_KIND_TK_TOEZEGGING = "tk-toezegging"
RAW_KIND_TK_COMMISSIE = "tk-commissie"
RAW_KIND_TK_PERSOON = "tk-persoon"
RAW_KIND_TK_DOCUMENT = "tk-document"
# The links of a Document alone (its activities, attachments and the letters it is an
# attachment of): ``retrieve tk-document-links``.
RAW_KIND_TK_DOCUMENT_LINKS = "tk-document-links"
# The actors of a Zaak alone (its submitters and lead committee): ``retrieve tk-case-actors``.
RAW_KIND_TK_CASE_ACTORS = "tk-case-actors"
RAW_KIND_TK_FRACTIE = "tk-fractie"
RAW_KIND_TK_FRACTIEZETELPERSOON = "tk-fractie-zetel-persoon"
# A seat of a faction no member held (FractieZetelVacature): between a member who left and
# the successor's installation.
RAW_KIND_TK_FRACTIEZETELVACATURE = "tk-fractie-zetel-vacature"
# The XML of a Kamerstuk in the KOOP repository (source ``tk``, external id ``kst-<dossier>-<n>``).
RAW_KIND_TK_KAMERSTUK_XML = "tk-kamerstuk-xml"
RAW_KIND_RS_CONTENT = "rs-content"
# The Instanties value list of the Rechtspraak (external id: Instanties).
RAW_KIND_RS_INSTANTIES = "rs-instanties-xml"
RAW_KIND_EU_CELEX = "eu-celex-html"
# A national implementing measure of the Netherlands in CELLAR (external id: its document id).
RAW_KIND_EU_NIM = "eu-nim-json"
RAW_KIND_BWB_TOESTAND = "bwb-toestand-xml"
RAW_KIND_BWB_TOESTAND_ALL = "bwb-toestand-xml-all"
# The ``<algemene-informatie>`` element of a WTI file (official abbreviations), not the file.
RAW_KIND_BWB_WTI_GENERAL = "bwb-wti-algemene-informatie-xml"
RAW_KIND_STB_AMVB = "stb-amvb-xml"
RAW_KIND_STCRT_REGELING = "stcrt-regeling-xml"
# How many publications of each ministry name a cabinet post (external id: the query).
RAW_KIND_STCRT_POST_CREATORS = "stcrt-post-creators-json"
RAW_KIND_ECHR_JUDGMENT = "echr-judgment-json"
# The ``word/document.xml`` of the DOCX HUDOC serves of a judgment (external id: its item id).
RAW_KIND_ECHR_TEXT = "echr-judgment-docx-xml"
RAW_KIND_EK_KAMERSTUK = "ek-kamerstuk-json"
# One day of the list of votes on bills of eerstekamer.nl (external id: the date), and the list
# of the bills the Eerste Kamer rejected (external id: its path, both pages in one record).
RAW_KIND_EK_VOTES_DAY = "ek-votes-day-html"
RAW_KIND_EK_REJECTED = "ek-rejected-html"
# A page of eerstekamer.nl on its composition: the lists of factions and committees and the
# page of each (external id: its path); every run reads them all again.
RAW_KIND_EK_COMPOSITION = "ek-composition-html"
# The page of a bill on eerstekamer.nl (external id: its path), with the heading of the list
# of its committee it was found under (``meta.status``).
RAW_KIND_EK_BILL = "ek-bill-html"
# The agenda of a plenary sitting of the Eerste Kamer (external id: its path) and a day of its
# committee meetings (external id: the day, YYYY-MM-DD), from eerstekamer.nl.
RAW_KIND_EK_PLENARY = "ek-plenary-html"
RAW_KIND_EK_COMMITTEE_DAY = "ek-committee-day-html"
# A term of the list of changes in the composition of the Eerste Kamer (``/personele_mutaties``,
# external id its path) and the page of one change, a news item (external id its path).
RAW_KIND_EK_MUTATIONS = "ek-mutations-html"
RAW_KIND_EK_MUTATION = "ek-mutation-html"
RAW_KIND_EK_PERSON = "ek-person-html"
# The page of an election of the Eerste Kamer in the Kiesraad's databank (external id its
# code, ``EK20230530``): the seats each list won.
RAW_KIND_KIESRAAD_EK_RESULT = "kiesraad-ek-result-html"
RAW_KIND_VERDRAG = "verdrag-json"
# the item XML of a treaty: its parties, Tractatenbladen, dossiers and related treaties
RAW_KIND_VERDRAG_XML = "verdrag-xml"
# The page of one cabinet since 1945 on rijksoverheid.nl (external id: its slug).
RAW_KIND_RIJKSOVERHEID_CABINET = "rijksoverheid-cabinet-html"
# The TOOI value list of every ministry (external id: rwc_ministeries_compleet).
RAW_KIND_TOOI_MINISTRIES = "tooi-ministries-jsonld"
# A thesaurus of the BWB (external id the name of its list).
RAW_KIND_TOOI_THESAURUS = "tooi-thesaurus-jsonld"
TOOI_BWB_LEGAL_AREAS = "scw_bwb_rechtsgebieden"
TOOI_BWB_THEMES = "scw_bwb_themas"

# A document the source answered HTTP 404 for is remembered as a record of the kind it would
# have had plus this suffix (no payload), so it is not asked for again on every run.
RAW_KIND_MISSING_SUFFIX = "-missing"

RAW_SOURCE_KINDS: dict[str, tuple[str, ...]] = {
    SOURCE_TK: (
        RAW_KIND_TK_ZAAK,
        RAW_KIND_TK_DOSSIER,
        RAW_KIND_TK_ACTIVITEIT,
        RAW_KIND_TK_STEMMING,
        RAW_KIND_TK_BESLUIT,
        RAW_KIND_TK_TOEZEGGING,
        RAW_KIND_TK_COMMISSIE,
        RAW_KIND_TK_PERSOON,
        RAW_KIND_TK_DOCUMENT,
        RAW_KIND_TK_DOCUMENT_LINKS,
        RAW_KIND_TK_CASE_ACTORS,
        RAW_KIND_TK_FRACTIE,
        RAW_KIND_TK_FRACTIEZETELPERSOON,
        RAW_KIND_TK_FRACTIEZETELVACATURE,
        RAW_KIND_TK_KAMERSTUK_XML,
    ),
    SOURCE_RECHTSPRAAK: (RAW_KIND_RS_CONTENT, RAW_KIND_RS_INSTANTIES),
    SOURCE_EURLEX: (RAW_KIND_EU_CELEX, RAW_KIND_EU_NIM),
    SOURCE_BWB: (
        RAW_KIND_BWB_TOESTAND,
        RAW_KIND_BWB_TOESTAND_ALL,
        RAW_KIND_BWB_WTI_GENERAL,
    ),
    SOURCE_STAATSBLAD: (RAW_KIND_STB_AMVB,),
    SOURCE_STAATSCOURANT: (RAW_KIND_STCRT_REGELING, RAW_KIND_STCRT_POST_CREATORS),
    SOURCE_ECHR: (RAW_KIND_ECHR_JUDGMENT, RAW_KIND_ECHR_TEXT),
    SOURCE_EERSTEKAMER: (
        RAW_KIND_EK_KAMERSTUK,
        RAW_KIND_EK_VOTES_DAY,
        RAW_KIND_EK_REJECTED,
        RAW_KIND_EK_COMPOSITION,
        RAW_KIND_EK_BILL,
        RAW_KIND_EK_PLENARY,
        RAW_KIND_EK_COMMITTEE_DAY,
        RAW_KIND_EK_MUTATIONS,
        RAW_KIND_EK_MUTATION,
        RAW_KIND_EK_PERSON,
    ),
    SOURCE_VERDRAGENBANK: (RAW_KIND_VERDRAG, RAW_KIND_VERDRAG_XML),
    SOURCE_RIJKSOVERHEID: (RAW_KIND_RIJKSOVERHEID_CABINET,),
    SOURCE_TOOI: (RAW_KIND_TOOI_MINISTRIES, RAW_KIND_TOOI_THESAURUS),
    SOURCE_KIESRAAD: (RAW_KIND_KIESRAAD_EK_RESULT,),
}

# ── Semantic pipeline limits ──────────────────────────────────────────────────

# Maximum characters of a document's text scanned for citations (200 KB).
MAX_SEMANTIC_TEXT_LENGTH = 200_000

# Longest title / display name stored on a node (longer source titles are truncated).
MAX_TITLE_CHARS = 200

# ── Request pacing ────────────────────────────────────────────────────────────
# Minimum seconds between two requests to one host, in every client (clients/pacing.py).
# A host that answers HTTP 429 or 503 makes the interval grow, and it shrinks back to this
# value while requests succeed. repository.overheid.nl was measured on 2026-09-20: it
# throttles from about 5 requests per second sustained (a bucket of about 20).
DEFAULT_MIN_INTERVAL = 0.2
HOST_MIN_INTERVAL: dict[str, float] = {
    "repository.overheid.nl": 0.5,
    "hudoc.echr.coe.int": 0.5,
    "publications.europa.eu": 0.3,
    # Rechtspraak allows "niet meer dan 10 requests per seconde" and asks to mind the others.
    "data.rechtspraak.nl": 0.125,
    "gegevensmagazijn.tweedekamer.nl": 0.1,
    "zoekservice.overheid.nl": 0.1,
    "repository.officiele-overheidspublicaties.nl": 0.1,
    # a page at a time with a pause: 33 pages, read seldom
    "www.rijksoverheid.nl": 2.0,
    # the lists of eerstekamer.nl: 106 pages of votes, read seldom
    "www.eerstekamer.nl": 2.0,
    # six pages of the Kiesraad's databank, read once
    "www.verkiezingsuitslagen.nl": 2.0,
}

# ── Rechtspraak courts ────────────────────────────────────────────────────────
# A court to read is an ECLI code or a tier of the court table (``core.courts.owms_terms``).
# Every court the index holds (no ``creator`` filter): the rechtbanken, the special courts
# and those that no longer exist too.
RECHTSPRAAK_EVERY_COURT = "all"
RECHTSPRAAK_DEFAULT_COURTS = (RECHTSPRAAK_EVERY_COURT,)
# Judgments are published up to weeks after the decision date; an incremental run looks this
# far before its ``--since``.
RECHTSPRAAK_PUBLICATION_LAG_DAYS = 30
# A judgment published later than that lag, and one that is corrected, is only found by
# when it was modified. Up to this many days back that listing is selective (Hoge Raad, a
# week: 44 decided, 107 modified); further back it matches the mass republication of the
# corpus (a year: 2,128 decided, 5,830 modified), so long windows list by decision date only.
RECHTSPRAAK_MODIFIED_WINDOW_DAYS = 60

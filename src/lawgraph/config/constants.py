"""Names used across LawGraph: collections, relation types, source ids, raw kinds."""

from __future__ import annotations

from pathlib import Path
from typing import Final, Literal, get_args

# The data the package carries: the tables built from the sources and, under ``curated/``,
# the lists kept by hand (``core.curated``).
DATA_DIR = Path(__file__).resolve().parents[1] / "data"

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

# The collections of the nodes (``core.models.COLLECTIONS``), as the API types them.
Collection = Literal[
    "instruments",
    "articles",
    "instrument_versions",
    "article_versions",
    "cases",
    "documents",
    "judgments",
    "dossiers",
    "activities",
    "decisions",
    "commitments",
    "committees",
    "members",
    "factions",
    "cabinets",
    "annexes",
]
COLLECTION_NAMES: tuple[Collection, ...] = get_args(Collection)


def as_collection(value: str) -> Collection:
    """*value*, the name of a collection of nodes; a ValueError for any other."""
    for name in COLLECTION_NAMES:
        if name == value:
            return name
    raise ValueError(f"no collection of nodes: {value!r}")


# ── Edge status values ────────────────────────────────────────────────────────

EdgeStatus = Literal["canoniek", "voorgesteld"]
EDGE_STATUS_CANONIEK: Final[EdgeStatus] = "canoniek"  # current law
# A pending mutation from an open dossier.
EDGE_STATUS_VOORGESTELD: Final[EdgeStatus] = "voorgesteld"

# ── Relation type constants ───────────────────────────────────────────────────
# One constant per relation in ``core.relations.RELATIONS``; the names and their
# meaning live in that catalogue. Relation strings are written nowhere else.

RELATION_PART_OF: Final = "PART_OF"
RELATION_VERSION_OF: Final = "VERSION_OF"
RELATION_ESTABLISHES: Final = "ESTABLISHES"
RELATION_AMENDS: Final = "AMENDS"
RELATION_INTRODUCES: Final = "INTRODUCES"
RELATION_REPEALS: Final = "REPEALS"
RELATION_TRANSPOSED_TO: Final = "TRANSPOSED_TO"
RELATION_BASED_ON: Final = "BASED_ON"
RELATION_IMPLEMENTS: Final = "IMPLEMENTS"
RELATION_LEGISLATED_IN: Final = "LEGISLATED_IN"
RELATION_PUBLISHED_IN: Final = "PUBLISHED_IN"
RELATION_REFERS_TO: Final = "REFERS_TO"
RELATION_EXPLAINS: Final = "EXPLAINS"
RELATION_APPEAL_OF: Final = "APPEAL_OF"
RELATION_CONTINUES: Final = "CONTINUES"
RELATION_REFERRED_BY: Final = "REFERRED_BY"
RELATION_ADVISES_ON: Final = "ADVISES_ON"
RELATION_ANSWERS: Final = "ANSWERS"
RELATION_SAME_AS: Final = "SAME_AS"
RELATION_SCOPED_BY: Final = "SCOPED_BY"
RELATION_ABOUT: Final = "ABOUT"
RELATION_LED_BY: Final = "LED_BY"
RELATION_MADE_IN: Final = "MADE_IN"
RELATION_MEMBER_OF: Final = "MEMBER_OF"
RELATION_AUTHORED: Final = "AUTHORED"
RELATION_VOTED: Final = "VOTED"
RELATION_RELATED_TO: Final = "RELATED_TO"
RELATION_REVISES: Final = "REVISES"
RELATION_ACCOMPANIES: Final = "ACCOMPANIES"
RELATION_SECOND_READING_OF: Final = "SECOND_READING_OF"
RELATION_SERVED_IN: Final = "SERVED_IN"

# The relations (``core.relations.RELATIONS``), as the API types them.
Relation = Literal[
    "PART_OF",
    "VERSION_OF",
    "ESTABLISHES",
    "AMENDS",
    "INTRODUCES",
    "REPEALS",
    "TRANSPOSED_TO",
    "BASED_ON",
    "IMPLEMENTS",
    "LEGISLATED_IN",
    "PUBLISHED_IN",
    "REFERS_TO",
    "EXPLAINS",
    "APPEAL_OF",
    "CONTINUES",
    "REFERRED_BY",
    "ADVISES_ON",
    "ANSWERS",
    "SAME_AS",
    "SCOPED_BY",
    "ABOUT",
    "LED_BY",
    "MADE_IN",
    "MEMBER_OF",
    "SERVED_IN",
    "AUTHORED",
    "RELATED_TO",
    "REVISES",
    "ACCOMPANIES",
    "SECOND_READING_OF",
    "VOTED",
]
RELATION_LITERALS: tuple[Relation, ...] = get_args(Relation)


def as_relation(value: str) -> Relation:
    """*value*, the name of a relation; a ValueError for any other."""
    for name in RELATION_LITERALS:
        if name == value:
            return name
    raise ValueError(f"no relation: {value!r}")


# What a law or a bill does to an article: changes it, or (enacting a regulation) sets it;
# and what a publication does, its nota van toelichting included.
CHANGE_RELATIONS = (RELATION_AMENDS, RELATION_INTRODUCES, RELATION_REPEALS)
ENACTING_RELATIONS = (RELATION_ESTABLISHES, *CHANGE_RELATIONS)
PUBLICATION_RELATIONS = (*ENACTING_RELATIONS, RELATION_EXPLAINS)

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
# The judgments of the courts of the European Union: records of ``eurlex`` (sector 6).
SOURCE_CJEU = "cjeu"
SOURCE_EERSTEKAMER = "eerstekamer"
SOURCE_VERDRAGENBANK = "verdragenbank"
SOURCE_RIJKSOVERHEID = "rijksoverheid"
SOURCE_TOOI = "tooi"
SOURCE_KIESRAAD = "kiesraad"
# The label of a member only Rijksoverheid knows: a bewindspersoon without a Tweede Kamer person.
LABEL_RIJKSOVERHEID = "Rijksoverheid"

# The chambers of the States General, as a document or decision carries them in its labels.
Chamber = Literal["TK", "EK"]
CHAMBER_TK: Final[Chamber] = "TK"
CHAMBER_EK: Final[Chamber] = "EK"
CHAMBERS: tuple[Chamber, ...] = get_args(Chamber)
# The label the nodes taken over from the Eerste Kamer carry besides ``CHAMBER_EK``.
LABEL_EERSTE_KAMER = "EersteKamer"

# A document is explanatory (an MvT, NvT, nota van toelichting) when its ``props.kind``
# contains this, in any case. SQL and ``core.documents.is_explanatory`` both use it.
EXPLANATORY_KIND_MARKER = "toelichting"

# The edge `source` of IMPLEMENTS (and of the REFERS_TO from a regulation to an EU act its
# text names without implementing it), with the basis of an IMPLEMENTS edge in its `meta`:
# the name of ``semantic bwb-implements``, which the readers of ``db/queries`` filter on.
EDGE_SOURCE_BWB_IMPLEMENTS = "bwb-implements"
# The kinds of a treaty instrument of the Verdragenbank, by the parties to it.
KIND_TREATY = "verdrag"
KIND_BILATERAL_TREATY = "bilateraalverdrag"
KIND_MULTILATERAL_TREATY = "multilateraalverdrag"
TREATY_KINDS = (KIND_TREATY, KIND_BILATERAL_TREATY, KIND_MULTILATERAL_TREATY)
# What an IMPLEMENTS edge rests on (`meta.bases`).
ImplementsBasis = Literal["national_implementing_measure", "considerans"]
IMPLEMENTS_BASIS_NIM: Final[ImplementsBasis] = "national_implementing_measure"
IMPLEMENTS_BASIS_CONSIDERANS: Final[ImplementsBasis] = "considerans"
IMPLEMENTS_BASES: tuple[ImplementsBasis, ...] = get_args(ImplementsBasis)

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
# The PDF of an attachment of a Kamerstuk that is a transposition table (external id
# ``blg-1081574``), base64 in the text payload.
RAW_KIND_TK_TRANSPOSITION_TABLE = "tk-transposition-table-pdf"
# The XML of a Kamerstuk whose text names a transposition table (external id
# ``kst-<dossier>-<n>``): with its XML when a table is read in it, without it otherwise.
RAW_KIND_TK_TRANSPOSITION_DOCUMENT = "tk-transposition-document-xml"
RAW_KIND_RECHTSPRAAK_CONTENT = "rs-content"
# The Instanties value list of the Rechtspraak (external id: Instanties).
RAW_KIND_RECHTSPRAAK_INSTANTIES = "rs-instanties-xml"
RAW_KIND_EURLEX_CELEX = "eu-celex-html"
# A national implementing measure of the Netherlands in CELLAR (external id: its document id).
RAW_KIND_EURLEX_NIM = "eu-nim-json"
RAW_KIND_BWB_TOESTAND = "bwb-toestand-xml"
RAW_KIND_BWB_TOESTAND_ALL = "bwb-toestand-xml-all"
# The ``<algemene-informatie>`` element of a WTI file (official abbreviations), not the file.
RAW_KIND_BWB_WTI_GENERAL = "bwb-wti-algemene-informatie-xml"
RAW_KIND_STAATSBLAD_AMVB = "stb-amvb-xml"
# A law of the Staatsblad (``DC.type`` ``Wet``) of a dossier the graph holds as adopted.
RAW_KIND_STAATSBLAD_LAW = "stb-wet-xml"
RAW_KIND_STAATSCOURANT_REGELING = "stcrt-regeling-xml"
# How many publications of each ministry name a cabinet post (external id: the query).
RAW_KIND_STAATSCOURANT_POST_CREATORS = "stcrt-post-creators-json"
RAW_KIND_ECHR_JUDGMENT = "echr-judgment-json"
# The ``word/document.xml`` of the DOCX HUDOC serves of a judgment (external id: its item id).
RAW_KIND_ECHR_TEXT = "echr-judgment-docx-xml"
RAW_KIND_EERSTEKAMER_KAMERSTUK = "ek-kamerstuk-json"
# One day of the list of votes on bills of eerstekamer.nl (external id: the date), and the list
# of the bills the Eerste Kamer rejected (external id: its path, both pages in one record).
RAW_KIND_EERSTEKAMER_VOTES_DAY = "ek-votes-day-html"
RAW_KIND_EERSTEKAMER_REJECTED = "ek-rejected-html"
# A page of eerstekamer.nl on its composition: the lists of factions and committees and the
# page of each, stored once per day its content changed (external id: ``<path>@<day>``).
RAW_KIND_EERSTEKAMER_COMPOSITION = "ek-composition-html"
# The composition of the Eerste Kamer as observed before its pages were kept per version:
# its factions, committees, members and MEMBER_OF edges with their periods, and the versions
# it covers (one record, external id ``observed``).
RAW_KIND_EERSTEKAMER_COMPOSITION_OBSERVED = "ek-composition-observed"
# The page of a bill on eerstekamer.nl (external id: its path), with the heading of the list
# of its committee it was found under (``meta.status``).
RAW_KIND_EERSTEKAMER_BILL = "ek-bill-html"
# The agenda of a plenary sitting of the Eerste Kamer (external id: its path) and a day of its
# committee meetings (external id: the day, YYYY-MM-DD), from eerstekamer.nl.
RAW_KIND_EERSTEKAMER_PLENARY = "ek-plenary-html"
RAW_KIND_EERSTEKAMER_COMMITTEE_DAY = "ek-committee-day-html"
# A term of the list of changes in the composition of the Eerste Kamer (``/personele_mutaties``,
# external id its path) and the page of one change, a news item (external id its path).
RAW_KIND_EERSTEKAMER_MUTATIONS = "ek-mutations-html"
RAW_KIND_EERSTEKAMER_MUTATION = "ek-mutation-html"
RAW_KIND_EERSTEKAMER_PERSON = "ek-person-html"
# The page of a motion of the Eerste Kamer (``/motiedossier/…``, external id its path): what it
# asks, its key data and who submitted and co-signed it.
RAW_KIND_EERSTEKAMER_MOTION = "ek-motion-html"
# The page of an election of the Eerste Kamer in the Kiesraad's databank (external id its
# code, ``EK20230530``): the seats each list won.
RAW_KIND_KIESRAAD_EK_RESULT = "kiesraad-ek-result-html"
RAW_KIND_VERDRAGENBANK_JSON = "verdrag-json"
# the item XML of a treaty: its parties, Tractatenbladen, dossiers and related treaties
RAW_KIND_VERDRAGENBANK_XML = "verdrag-xml"
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
        RAW_KIND_TK_TRANSPOSITION_TABLE,
        RAW_KIND_TK_TRANSPOSITION_DOCUMENT,
    ),
    SOURCE_RECHTSPRAAK: (RAW_KIND_RECHTSPRAAK_CONTENT, RAW_KIND_RECHTSPRAAK_INSTANTIES),
    SOURCE_EURLEX: (RAW_KIND_EURLEX_CELEX, RAW_KIND_EURLEX_NIM),
    SOURCE_BWB: (
        RAW_KIND_BWB_TOESTAND,
        RAW_KIND_BWB_TOESTAND_ALL,
        RAW_KIND_BWB_WTI_GENERAL,
    ),
    SOURCE_STAATSBLAD: (RAW_KIND_STAATSBLAD_AMVB, RAW_KIND_STAATSBLAD_LAW),
    SOURCE_STAATSCOURANT: (
        RAW_KIND_STAATSCOURANT_REGELING,
        RAW_KIND_STAATSCOURANT_POST_CREATORS,
    ),
    SOURCE_ECHR: (RAW_KIND_ECHR_JUDGMENT, RAW_KIND_ECHR_TEXT),
    SOURCE_EERSTEKAMER: (
        RAW_KIND_EERSTEKAMER_KAMERSTUK,
        RAW_KIND_EERSTEKAMER_VOTES_DAY,
        RAW_KIND_EERSTEKAMER_REJECTED,
        RAW_KIND_EERSTEKAMER_COMPOSITION,
        RAW_KIND_EERSTEKAMER_COMPOSITION_OBSERVED,
        RAW_KIND_EERSTEKAMER_BILL,
        RAW_KIND_EERSTEKAMER_PLENARY,
        RAW_KIND_EERSTEKAMER_COMMITTEE_DAY,
        RAW_KIND_EERSTEKAMER_MUTATIONS,
        RAW_KIND_EERSTEKAMER_MUTATION,
        RAW_KIND_EERSTEKAMER_PERSON,
        RAW_KIND_EERSTEKAMER_MOTION,
    ),
    SOURCE_VERDRAGENBANK: (RAW_KIND_VERDRAGENBANK_JSON, RAW_KIND_VERDRAGENBANK_XML),
    SOURCE_RIJKSOVERHEID: (RAW_KIND_RIJKSOVERHEID_CABINET,),
    SOURCE_TOOI: (RAW_KIND_TOOI_MINISTRIES, RAW_KIND_TOOI_THESAURUS),
    SOURCE_KIESRAAD: (RAW_KIND_KIESRAAD_EK_RESULT,),
}

# Records of a kind read in one cursor batch: fewer the larger its payload (a whole act
# or judgment), more for the small JSON of a TK record.
RAW_BATCH_SIZE: dict[str, int] = {
    RAW_KIND_TK_ZAAK: 1000,
    RAW_KIND_TK_DOSSIER: 1000,
    RAW_KIND_TK_ACTIVITEIT: 1000,
    RAW_KIND_TK_STEMMING: 1000,
    RAW_KIND_TK_BESLUIT: 1000,
    RAW_KIND_TK_TOEZEGGING: 1000,
    RAW_KIND_TK_COMMISSIE: 1000,
    RAW_KIND_TK_PERSOON: 1000,
    RAW_KIND_TK_DOCUMENT: 1000,
    RAW_KIND_TK_DOCUMENT_LINKS: 5000,
    RAW_KIND_TK_CASE_ACTORS: 5000,
    RAW_KIND_TK_FRACTIE: 1000,
    RAW_KIND_TK_FRACTIEZETELPERSOON: 1000,
    RAW_KIND_TK_FRACTIEZETELVACATURE: 1000,
    RAW_KIND_TK_KAMERSTUK_XML: 20,
    RAW_KIND_TK_TRANSPOSITION_TABLE: 1,
    RAW_KIND_TK_TRANSPOSITION_DOCUMENT: 1,
    RAW_KIND_RECHTSPRAAK_CONTENT: 200,
    RAW_KIND_RECHTSPRAAK_INSTANTIES: 500,
    RAW_KIND_EURLEX_CELEX: 20,
    RAW_KIND_EURLEX_NIM: 50,
    RAW_KIND_BWB_TOESTAND: 20,
    RAW_KIND_BWB_TOESTAND_ALL: 20,
    RAW_KIND_BWB_WTI_GENERAL: 1000,
    RAW_KIND_STAATSBLAD_AMVB: 20,
    RAW_KIND_STAATSBLAD_LAW: 5,
    RAW_KIND_STAATSCOURANT_REGELING: 20,
    RAW_KIND_STAATSCOURANT_POST_CREATORS: 200,
    RAW_KIND_ECHR_JUDGMENT: 20,
    RAW_KIND_ECHR_TEXT: 20,
    RAW_KIND_EERSTEKAMER_KAMERSTUK: 1000,
    RAW_KIND_EERSTEKAMER_VOTES_DAY: 50,
    RAW_KIND_EERSTEKAMER_REJECTED: 50,
    RAW_KIND_EERSTEKAMER_COMPOSITION: 20,
    RAW_KIND_EERSTEKAMER_COMPOSITION_OBSERVED: 1,
    RAW_KIND_EERSTEKAMER_BILL: 50,
    RAW_KIND_EERSTEKAMER_PLENARY: 50,
    RAW_KIND_EERSTEKAMER_COMMITTEE_DAY: 50,
    RAW_KIND_EERSTEKAMER_MUTATIONS: 50,
    RAW_KIND_EERSTEKAMER_MUTATION: 20,
    RAW_KIND_EERSTEKAMER_PERSON: 50,
    RAW_KIND_EERSTEKAMER_MOTION: 50,
    RAW_KIND_KIESRAAD_EK_RESULT: 20,
    RAW_KIND_VERDRAGENBANK_JSON: 1000,
    RAW_KIND_VERDRAGENBANK_XML: 1000,
    RAW_KIND_RIJKSOVERHEID_CABINET: 50,
    RAW_KIND_TOOI_MINISTRIES: 500,
    RAW_KIND_TOOI_THESAURUS: 10,
}

# ── Semantic pipeline limits ──────────────────────────────────────────────────

# Maximum characters of a document's text scanned for citations (200 KB).
MAX_SEMANTIC_TEXT_LENGTH = 200_000

# Longest title / display name stored on a node (longer source titles are truncated).
MAX_TITLE_CHARS = 200

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

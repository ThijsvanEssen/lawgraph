"""Typed props schemas for every ArangoDB collection.

Each node collection has a corresponding Pydantic model with ``extra="forbid"``.
This catches typos in field names (e.g. ``bwbr_id`` instead of ``bwb_id``) and
undeclared fields at Node construction time.

Rules for maintainers:
  1. All fields are Optional — props are merged across pipeline runs; no single
     pipeline writes every field on every pass.
  2. ``extra="forbid"`` is intentional — unknown field names raise ValidationError.
     If you legitimately need a new field, add it to the schema *first*.
  3. ``from_document()`` and ``with_key()`` bypass validation (DB reads and internal
     copies may carry partial data). Validation runs only when a fresh
     ``Node()`` is constructed in pipeline code.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from lawgraph.config.constants import (
    COLLECTION_ACTIVITIES,
    COLLECTION_ANNEXES,
    COLLECTION_ARTICLE_VERSIONS,
    COLLECTION_ARTICLES,
    COLLECTION_CABINETS,
    COLLECTION_CASES,
    COLLECTION_COMMITMENTS,
    COLLECTION_COMMITTEES,
    COLLECTION_DECISIONS,
    COLLECTION_DOCUMENTS,
    COLLECTION_DOSSIERS,
    COLLECTION_FACTIONS,
    COLLECTION_INSTRUMENT_VERSIONS,
    COLLECTION_INSTRUMENTS,
    COLLECTION_JUDGMENTS,
    COLLECTION_MEMBERS,
)


class _StrictBase(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _CommonProps(_StrictBase):
    """Fields present in nearly every collection's props."""

    display_name: str | None = None
    source: str | None = None
    stub: bool | None = None


# ---------------------------------------------------------------------------
# instruments
# ---------------------------------------------------------------------------


class InstrumentProps(_CommonProps):
    bwb_id: str | None = None
    celex: str | None = None
    title: str | None = None
    official_title: str | None = None
    citation_title: str | None = None
    short_title: str | None = None
    # a publication (``core.bwb_xml.publication_props``): its id at officielebekendmakingen.nl
    official_id: str | None = None
    # the abbreviation it is cited by (``core.aliases.abbreviation_of``): EVRM, AVG
    abbreviation: str | None = None
    # every name it is cited by: the WTI abbreviations and, for a book of a code, the forms
    # "Boek 6 BW", "6 BW", "BW 6", "BW6", "BW"
    aliases: list[str] | None = None
    jurisdiction: str | None = None
    kind: str | None = None
    lang: str | None = None
    meta: dict[str, Any] | None = None
    external_id: str | None = None
    uri: str | None = None
    title_nl: str | None = None
    title_en: str | None = None
    treaty_number: str | None = None
    treaty_type: str | None = None
    status: str | None = None
    in_force: bool | None = None
    date_signed: str | None = None  # of the instrument itself, not of an amendment
    date_in_force: str | None = None
    version_date_in_force: str | None = None  # BWB: the start of the toestand in force
    parties: list[str] | None = None
    article_count: int | None = None
    inbound_citation_count: int | None = None
    date_eff: str | None = None
    # amending publications (Stb/Trb/…) modelled as instruments, and the dossiers of a statute
    publication_kind: str | None = None
    publication_year: int | None = None
    publication_number: str | None = None
    date_published: str | None = None
    dossier_numbers: list[str] | None = None
    # what the toestand says the semantic steps link from (BASED_ON, IMPLEMENTS)
    basis: list[dict[str, Any]] | None = None  # "Gelet op": bwb_id, article, doc, text
    celex_refs: list[str] | None = None  # the EU acts the text names
    implements_celex: list[str] | None = (
        None  # those its considerans says it implements
    )
    enacted_publication: str | None = (
        None  # the publication that enacted it: stb-2018-144
    )


# ---------------------------------------------------------------------------
# articles
# ---------------------------------------------------------------------------


class ArticleProps(_CommonProps):
    bwb_id: str | None = None
    celex: str | None = None
    article_number: str | None = None  # null for an article with only a heading
    label: str | None = None  # "Artikel 287", or the heading: "Algemene bepaling"
    heading: str | None = (
        None  # the title of its kop ("Definities"), when the BWB has one
    )
    position: int | None = None  # its place in the current toestand: the order of lists
    title: str | None = None
    text: str | None = None
    instrument_citation_title: str | None = None
    # the ``abbreviation`` of its instrument: "art. 8 EVRM"
    instrument_abbreviation: str | None = None
    instrument_id: str | None = None
    # BWB identity and provenance of the current version
    stam_id: str | None = None
    versie_id: str | None = None
    valid_from: str | None = None
    source_publication: str | None = None  # e.g. "Stb.2019-33"
    repealed: bool | None = None
    last_article_number: str | None = None  # historical identities only
    parts: list[dict[str, Any]] | None = (
        None  # aanhef, leden, onderdelen: id, kind, number, start, end
    )
    references: list[dict[str, Any]] | None = None  # structured refs from the XML
    breadcrumb: list[dict[str, Any]] | None = None  # divisions: type, label, title


# ---------------------------------------------------------------------------
# instrument_versions
# ---------------------------------------------------------------------------


class InstrumentVersionProps(_CommonProps):
    bwb_id: str | None = None
    valid_from: str | None = None
    valid_until: str | None = None
    current: bool | None = None
    state_url: str | None = None


# ---------------------------------------------------------------------------
# article_versions
# ---------------------------------------------------------------------------


class ArticleVersionProps(_CommonProps):
    bwb_id: str | None = None
    # the start of the latest toestand that holds this version (normalize bwb-history)
    last_seen: str | None = None
    article_number: str | None = None
    label: str | None = None
    heading: str | None = None
    position: int | None = None  # its place in the toestand it was read from
    valid_from: str | None = None
    valid_until: str | None = None
    current: bool | None = None
    text: str | None = None
    instrument_citation_title: str | None = None
    stam_id: str | None = None
    versie_id: str | None = None
    path: str | None = None
    parts: list[dict[str, Any]] | None = None  # as on Article: offsets into ``text``
    effect: str | None = None  # BWB effect: nieuw / wijziging / vervallen …
    source_publication: str | None = None  # bron, e.g. "Stb.2019-33"
    origin_publication: dict[str, Any] | None = None  # Publication.to_dict()
    commencement_publication: dict[str, Any] | None = None
    # label, heading, place and text: equal for a version that only repeats the one before
    content_digest: str | None = None


# ---------------------------------------------------------------------------
# judgments
# ---------------------------------------------------------------------------


class JudgmentParagraphProps(_StrictBase):
    """One paragraph of a judgment (``core.judgments.extract_sections``)."""

    id: str  # ``rov-5.3``, ``kop-5``, ``p-3f2a9c1e``: unique in the judgment, for deep links
    number: str | None = None  # as printed, without its closing dot: "5.3"
    kind: Literal["heading", "subheading", "body", "signature"]
    text: str


class JudgmentRepresentativeProps(_StrictBase):
    """Who acts for a party of a judgment, as its kop names them."""

    name: str  # "mr. H.J.W. Alt"
    role: Literal["advocaat", "gemachtigde"]


class JudgmentPartyProps(_StrictBase):
    """One party of a judgment (``core.judgment_parties.read_parties``)."""

    name: str  # as the judgment writes it, anonymised where the source is: "[eiser]"
    role: str  # "Eiser", "Verdachte", ...; "Partij" when none applies
    roles: list[str] = []  # every role the judgment names, in its order; [role] if none
    role_stated: bool  # the judgment names the role; false when derived
    side: Literal["first", "second", "other"]
    alias: str | None = None  # what the judgment calls it: "EBN"
    representatives: list[JudgmentRepresentativeProps] = []


class JudgmentAppealTargetProps(_StrictBase):
    """A decision an appeal says it appeals that is not loaded (``core.appeals``)."""

    court: str  # as the text writes it: "rechtbank Gelderland"
    date: str  # ISO
    case_number: str | None = None  # as the text writes it: "24/6811"


class JudgmentUnresolvedCitationProps(_StrictBase):
    """A citation of a law that is not in the graph (``semantic rechtspraak``,
    ``core.mentions.ArticleMentions.unresolved``)."""

    law: str  # as the text writes it: "Rv", "Vw 2000"
    article_number: str
    raw_match: str  # the first citation: "art. 392 Rv"
    qualifier: str | None = None  # of the first citation: "derde lid"
    leden: list[str] = []
    onderdelen: list[str] = []
    aanhef: bool = False
    paragraph_ids: list[str] = []
    mention_count: int = 1


class JudgmentProps(_CommonProps):
    ecli: str | None = None
    source_kind: str | None = None
    meta: dict[str, Any] | None = None
    # the Dutch inhoudsindicatie; an English one (a translation) is ``summary_en``
    summary: str | None = None
    summary_en: str | None = None
    # an English translation: the ECLI of the judgment it translates
    translation_of: str | None = None
    # what lawyers call it ("Haviltex"; ``core.judgment_names``)
    names: list[str] | None = None
    # arrest, vonnis, beschikking, uitspraak, conclusie, prejudiciële beslissing
    # (``core.judgments.decision_kind``)
    decision_kind: str | None = None
    text: str | None = None
    judgment_metadata: dict[str, Any] | None = None
    subjects: list[str] | None = None
    paragraphs: list[JudgmentParagraphProps] | None = None
    # read from the kop; [] when it names none, absent when not read yet
    parties: list[JudgmentPartyProps] | None = None
    # a conclusion: the advocate-general who wrote it, as its kop names them
    # (``core.judgments.advocate_general``)
    advocate_general: str | None = None
    # and the role they sign in (``core.judgments.advocate_general_role``)
    advocate_general_role: str | None = None
    court: str | None = None
    case_number: str | None = None
    # ``case_number`` split and written as compared (``core.judgments.case_number_keys``)
    case_number_keys: list[str] | None = None
    # the earlier instances the metadata names (``dcterms:relation``)
    related_eclis: list[str] | None = None
    # the conclusion of a judgment, or the judgment of a conclusion (``psi:type`` conclusie)
    conclusion_eclis: list[str] | None = None
    # the decisions an appeal names in its text that are not loaded
    # (``semantic rechtspraak-appeal``); null when there are none
    unresolved_appeal_targets: list[JudgmentAppealTargetProps] | None = None
    # the citations of laws that are not in the graph (``semantic rechtspraak``), in reading
    # order; null when there are none
    unresolved_citations: list[JudgmentUnresolvedCitationProps] | None = None
    court_code: str | None = None
    # the coarse tier (the Type of the Instanties list) and the kind of court within it
    tier: str | None = None
    court_kind: str | None = None
    date_eff: str | None = None
    # "Datum publicatie" on uitspraken.rechtspraak.nl (``core.judgments.published_on``)
    published_on: str | None = None
    inbound_citation_count: int | None = None
    # the judgments its text cites (``semantic graph-list-stats``)
    outbound_citation_count: int | None = None
    # ``dcterms:isReplacedBy``: the ECLI of the publication of the same decision that
    # replaces this one
    replaced_by: str | None = None
    # that publication, when it is loaded (``semantic rechtspraak-duplicates``): this one
    # is ``SAME_AS`` it and left out of the lists
    same_as: str | None = None
    # parallel cases of one court and day (``semantic rechtspraak-series``): the lowest
    # ECLI of the series and how many judgments it has
    series_id: str | None = None
    series_size: int | None = None
    # ECHR-specific fields
    external_id: str | None = None
    appno: str | None = None
    title: str | None = None
    date: str | None = None
    respondent: str | None = None
    originating_body: str | None = None
    articles: list[str] | None = None
    conclusion: str | None = None
    importance: int | None = None


# ---------------------------------------------------------------------------
# documents  (TK, TK-dossier docs, Staatsblad, Staatscourant, Eerste Kamer)
# ---------------------------------------------------------------------------


class DocumentProps(_CommonProps):
    external_id: str | None = None
    raw: dict[str, Any] | None = None
    title: str | None = None
    # a paper named by its own subject (a motie, a letter): the title of its dossier
    dossier_title: str | None = None
    subject: str | None = None
    kind: str | None = None
    date: str | None = None
    # the document's own number: a Kamerstuk number, or a Stcrt/Stb one
    number: str | None = None
    text: str | None = None
    # ``normalize tk-content``: the structure of a Kamerstuk's text (core/kamerstuk_xml.py)
    text_source: str | None = None  # "kst-xml"
    text_truncated: bool | None = None
    xml_dialect: str | None = None  # "kamerwrk" | "officiele-publicatie"
    structure_quality: str | None = None  # "explicit" | "implicit" | "none"
    budget: bool | None = (
        None  # a budget or annual report: policy articles, not law articles
    )
    sections: list[dict[str, Any]] | None = None
    footnotes: list[dict[str, Any]] | None = None
    # TK-dossier documents
    dossier_number: str | None = None
    # the addition to the dossier number, e.g. the chapter "VII" of "35925 VII"
    dossier_suffix: str | None = None
    dossier_numbers: list[str] | None = None
    case_ids: list[str] | None = None
    # the Zaak.Soort of those cases (Wetgeving, Motie, Brief regering, ...)
    case_kinds: list[str] | None = None
    sequence: int | None = None
    session_year: str | None = None
    # Document.DocumentNummer (2026D44984): what tweedekamer.nl finds it by
    document_number: str | None = None
    actors: list | None = None
    # Eerste Kamer: the page of the paper on zoek.officielebekendmakingen.nl
    url: str | None = None
    # Staatsblad / Staatscourant
    identifier: str | None = None
    year: str | None = None
    bwb_id: str | None = None


# ---------------------------------------------------------------------------
# dossiers
# ---------------------------------------------------------------------------


class DossierProps(_CommonProps):
    external_id: str | None = None
    number: str | None = None
    suffix: str | None = None
    label: str | None = None
    order: str | None = None  # core.dossier_numbers.dossier_order: the Kamer's order
    title: str | None = None
    title_source: str | None = None
    closed: bool | None = None
    opened_on: str | None = None
    # where ``opened_on`` comes from: first_paper (nr. 1 of its own numbering),
    # royal_message (its Koninklijke boodschap) or earliest_record
    opened_on_basis: str | None = None
    # the day of its newest paper, held activity or decision (``dossier_stages``)
    last_activity: str | None = None
    # the GestartOp of its own zaak of a bill (Wetgeving, Initiatiefwetgeving, Begroting)
    submitted_on_tk: str | None = None
    closed_on: str | None = None
    case_kinds: list[str] | None = None
    # what it is (the Zaak.Soort of its own zaak, ``core.dossier_stages.dossier_kind``) and
    # where that comes from (``case`` or ``document``)
    kind: str | None = None
    kind_basis: str | None = None
    # of a bill: every phase of the curated list, ``{name, done, date}``, and the latest
    phases: list | None = None
    current_phase: str | None = None
    outcome: str | None = None
    # the last decision of the Kamer on its bill: ``{kind (BesluitSoort), text, date}``
    tk_decision: dict | None = None
    # the Eerste Kamer: the day it rejected the bill (its list of rejected bills: ``{date,
    # source_url, retrieved_on}``), and its outcome ``{outcome, date, method, source_url,
    # retrieved_on}``
    ek_rejected: dict | None = None
    ek_outcome: dict | None = None
    # who brought the dossier in (``semantic government``): the ministry (``core.ministries``)
    # of the first bewindspersoon to sign its earliest document, or ``initiative`` when a
    # Kamerlid signed first; the cabinet in office on that day
    ministry: str | None = None
    initiative: bool | None = None
    cabinet: str | None = None
    # the other dossiers with the same number (the chapters of one budget)
    same_number_count: int | None = None


# ---------------------------------------------------------------------------
# activities
# ---------------------------------------------------------------------------


class ActivityProps(_CommonProps):
    external_id: str | None = None
    date: str | None = None
    agenda_title: str | None = None
    kind: str | None = None
    # Activiteit.Status as the source writes it: Gepland, Uitgevoerd, Geannuleerd, ...
    status: str | None = None
    committee_id: str | None = None
    case_ids: list[str] | None = None
    dossier_numbers: list[str] | None = None
    case_kinds_by_dossier: dict[str, list[str]] | None = None
    number: str | None = None
    replaced_by: list[str] | None = None  # Activiteit.VervangenDoor: their numbers


# ---------------------------------------------------------------------------
# decisions
# ---------------------------------------------------------------------------


class DecisionProps(_CommonProps):
    # TK decisions
    decision_id: str | None = None
    agenda_item_id: str | None = None
    date: str | None = None
    subject: str | None = None
    agenda_item_subject: str | None = None
    decision_text: str | None = None
    # BesluitSoort as the Kamer writes it: Stemmen - aangenomen, Stemmen - zonder stemming
    # aannemen, Stemmen - uitstellen, ...
    decision_kind: str | None = None
    decision_order: int | None = None
    meeting_kind: str | None = None
    case_ids: list[str] | None = None
    primary_case_id: str | None = None
    # the Zaak.Soort of the primary case: Wetgeving on the vote on a bill itself
    primary_case_kind: str | None = None
    dossier_numbers: list[str] | None = None
    # "member" on a roll-call, "faction" otherwise; the tally is seats per
    # vote choice (members per choice on a roll-call) and voters is how many
    # cast each choice. Who voted how is on the VOTED edges.
    vote_kind: str | None = None
    tally: dict[str, int] | None = None
    voters: dict[str, int] | None = None
    passed: bool | None = None
    external_id: str | None = None
    # what was decided on: the Zaak.Soort of the primary case, or the one Soort of the
    # cases on its Agendapunt (``tk_records.decision_kind``)
    kind: str | None = None
    # ``TK``, or ``EK`` for a vote of the Eerste Kamer (``normalize eerstekamer-votes``)
    chamber: str | None = None
    # of a vote of the Eerste Kamer, as eerstekamer.nl writes them: the outcome it shows
    # (Aangenomen, Verworpen), how it was decided (Hamerstuk, Stemming bij zitten en opstaan,
    # aangenomen), the factions for, against and that asked to have their vote recorded, the
    # pages of the bill and of the report, and the day it was read; whether it is the vote
    # that decided the bill (``semantic tk-dossier-outcomes``)
    result: str | None = None
    method: str | None = None
    factions_for: list[str] | None = None
    factions_against: list[str] | None = None
    factions_noted: list[str] | None = None
    bill_url: str | None = None
    source_url: str | None = None
    retrieved_on: str | None = None
    bill_decision: bool | None = None


# ---------------------------------------------------------------------------
# commitments
# ---------------------------------------------------------------------------


class CommitmentProps(_CommonProps):
    external_id: str | None = None
    text: str | None = None
    minister_name: str | None = None
    minister_role: str | None = None
    # the ministry the Tweede Kamer gives the commitment (``Toezegging.Ministerie``)
    ministry_name: str | None = None
    made_on: str | None = None
    expected_resolution: str | None = None
    status: str | None = None
    activity_number: str | None = None
    number: str | None = None  # "TZ202603-130", how the Kamer cites it
    # who made it (``semantic government``): the member, the post and ministry of their
    # role, and the cabinet in office on the day
    member_key: str | None = None
    post: str | None = None
    ministry: str | None = None
    cabinet: str | None = None


# ---------------------------------------------------------------------------
# committees
# ---------------------------------------------------------------------------


class CommitteeProps(_CommonProps):
    external_id: str | None = None
    name: str | None = None
    abbreviation: str | None = None
    slug: str | None = None
    kind: str | None = None
    started_on: str | None = None
    ended_on: str | None = None
    # the open dossiers it leads, none once dissolved (``semantic graph-list-stats``)
    active_dossier_count: int | None = None
    # of the Eerste Kamer (``normalize eerstekamer-composition``): ``EK``; the page on
    # eerstekamer.nl and the day it was read; the first day a snapshot showed it and the
    # first that no longer did (not the day it began or ended)
    chamber: str | None = None
    url: str | None = None
    retrieved_on: str | None = None
    observed_from: str | None = None
    observed_until: str | None = None
    data_since: str | None = None  # the day of the first snapshot of the Eerste Kamer
    title: str | None = None  # the heading of its page: Commissie voor Financiën (FIN)


# ---------------------------------------------------------------------------
# members
# ---------------------------------------------------------------------------


class SourceRefProps(_StrictBase):
    """Where a cabinet or a post was read: ``rijksoverheid``, with the page and the day."""

    name: str | None = None
    url: str | None = None
    read_on: str | None = None


class PartyRefProps(_StrictBase):
    """A party as the source writes it (``VVD``, ``partijloos``), and its faction key."""

    short: str | None = None
    faction: str | None = None


class GovernmentFunctionProps(_StrictBase):
    """A post held in a cabinet (``normalize rijksoverheid``, ``core.cabinet_posts``)."""

    cabinet_key: str | None = None  # the cabinet node
    cabinet: str | None = None  # "kabinet-Rutte IV"
    function: str | None = (
        None  # "Minister van Infrastructuur en Waterstaat", as the source
    )
    also_named: list[str] | None = None  # the same post under another name
    post: str | None = None  # core.ministries.POSTS
    ministry: str | None = None  # a key of core.ministries.MINISTRIES
    # where the ministry comes from (core.post_ministries): page, tk_signatures,
    # tk_commitments, staatscourant; and why there is none: no_source, ambiguous
    ministry_source: str | None = None
    ministry_missing: str | None = None
    seat: str | None = None  # "ienw/minister"
    portfolio: str | None = None
    from_date: str | None = None
    to_date: str | None = None  # null while held
    from_date_source: str | None = None  # the day the source gives, null when none
    to_date_source: str | None = None
    corrected: list[str] | None = None  # which dates the rules of a seat set
    acting: bool | None = None  # a stand-in (ad interim)
    acting_reason: str | None = None  # source | held_other_seat
    acting_basis: str | None = None  # the words of the source
    acting_other_seat: dict[str, str] | None = None  # {seat, function}
    party: PartyRefProps | None = None
    overlaps_with: list[str] | None = (
        None  # member keys holding the seat at the same time
    )
    absent: list[str] | None = None  # (from, to) of a "tijdelijk afwezig"
    name: str | None = None  # the holder as the source writes them
    source: SourceRefProps | None = None


class MemberProps(_CommonProps):
    external_id: str | None = None
    name: str | None = None  # the name they go by: Persoon.Roepnaam and the surname
    full_name: str | None = None  # Persoon.Voornamen and the surname
    initials: str | None = None  # Persoon.Initialen: "S.Th.M."
    party: str | None = None
    faction_memberships: list | None = None
    family_name: str | None = None  # Persoon.Achternaam, without the tussenvoegsel
    name_prefix: str | None = None  # Persoon.Tussenvoegsel: "van der"
    number: str | None = None  # Persoon.Nummer
    slug: str | None = None  # a stable name for a readable URL (core.member_slugs)
    birth_date: str | None = None
    government_name: str | None = None  # "S.Th.M. Hermans", as Rijksoverheid writes it
    known_as: str | None = None  # "Sophie Hermans": the first name Rijksoverheid gives
    government_functions: list[GovernmentFunctionProps] | None = None
    # a member of the Eerste Kamer (``normalize eerstekamer-composition``): the name as its
    # page writes it, its page, its faction (key and abbreviation), the days served
    # (Anciënniteit), the place of residence, and the days it was first and last observed
    ek: dict | None = None


# ---------------------------------------------------------------------------
# cabinets
# ---------------------------------------------------------------------------


class CabinetPhaseProps(_StrictBase):
    """A phase of a cabinet (``core.cabinet_phases``)."""

    kind: str | None = None  # formatie, in_functie, demissionair, ... ; null: unknown
    from_date: str | None = None
    to_date: str | None = None
    label: str | None = None  # the source's own words
    source: SourceRefProps | None = None


class CabinetProps(_CommonProps):
    name: str | None = None  # "kabinet-Rutte IV"
    from_date: str | None = None
    to_date: str | None = None  # null while in office
    prime_minister: str | None = None  # member key
    previous: str | None = None  # the cabinet key before it
    parties: list[PartyRefProps] | None = None
    factions: list[str] | None = None  # the faction keys of its parties
    phases: list[CabinetPhaseProps] | None = None
    demissionary_from: str | None = None
    origin: SourceRefProps | None = None  # the page or the record it was read from


# ---------------------------------------------------------------------------
# factions
# ---------------------------------------------------------------------------


class FactionProps(_CommonProps):
    external_id: str | None = None  # the current Fractie record
    external_ids: list[str] | None = None  # every Fractie record of the faction
    name: str | None = None
    abbreviation: str | None = None
    aliases: list[str] | None = None
    active_from: str | None = None
    active_until: str | None = None
    seats: int | None = None
    # the day one of its seats last changed (FractieZetel.GewijzigdOp)
    seats_changed_on: str | None = None
    active: bool | None = None
    # of the Eerste Kamer (``normalize eerstekamer-composition``): ``EK``; the page on
    # eerstekamer.nl and the day it was read; the first day a snapshot showed it and the
    # first that no longer did (not the day it began or ended)
    chamber: str | None = None
    url: str | None = None
    retrieved_on: str | None = None
    observed_from: str | None = None
    observed_until: str | None = None
    data_since: str | None = None  # the day of the first snapshot of the Eerste Kamer
    # its board: ``{function, name, member (key), since}`` as the page gives it
    board: list | None = None


# ---------------------------------------------------------------------------
# cases (TK Zaken)
# ---------------------------------------------------------------------------


class RelatedCase(_StrictBase):
    id: str
    kind: str | None = None
    dossier_numbers: list[str] = []


class CaseProps(_CommonProps):
    external_id: str | None = None
    title: str | None = None
    citation_title: str | None = None
    number: str | None = None
    # Zaak.Soort: Wetgeving, Motie, Brief regering, ...
    kind: str | None = None
    dossier_numbers: list[str] | None = None
    started_on: str | None = None  # Zaak.GestartOp
    # Zaak.GerelateerdNaar: the cases the Kamer relates this one to
    related_cases: list[RelatedCase] | None = None


# ---------------------------------------------------------------------------
# annexes
# ---------------------------------------------------------------------------


class AnnexEntry(_StrictBase):
    index: int | None = None
    name: str | None = None
    description: str | None = None
    heading: str | None = None  # the paragraph introducing its list: "Gemeentewet"
    parent_index: int | None = None  # the entry it is nested in


class AnnexProps(_CommonProps):
    bwb_id: str | None = None
    label: str | None = None  # e.g. "I", "2", "A" — as cited in article text
    title: str | None = None
    description: str | None = None
    entries: list[AnnexEntry] | None = None
    instrument_id: str | None = None


# ---------------------------------------------------------------------------
# Registry — maps collection name → props validator class
# ---------------------------------------------------------------------------

COLLECTION_SCHEMAS: dict[str, type[_StrictBase]] = {
    COLLECTION_INSTRUMENTS: InstrumentProps,
    COLLECTION_ARTICLES: ArticleProps,
    COLLECTION_INSTRUMENT_VERSIONS: InstrumentVersionProps,
    COLLECTION_ARTICLE_VERSIONS: ArticleVersionProps,
    COLLECTION_JUDGMENTS: JudgmentProps,
    COLLECTION_DOCUMENTS: DocumentProps,
    COLLECTION_DOSSIERS: DossierProps,
    COLLECTION_ACTIVITIES: ActivityProps,
    COLLECTION_DECISIONS: DecisionProps,
    COLLECTION_COMMITMENTS: CommitmentProps,
    COLLECTION_COMMITTEES: CommitteeProps,
    COLLECTION_MEMBERS: MemberProps,
    COLLECTION_FACTIONS: FactionProps,
    COLLECTION_CABINETS: CabinetProps,
    COLLECTION_CASES: CaseProps,
    COLLECTION_ANNEXES: AnnexProps,
}

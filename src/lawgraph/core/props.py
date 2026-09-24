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
    COLLECTION_TOPICS,
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
    jurisdiction: str | None = None
    kind: str | None = None
    lang: str | None = None
    meta: dict[str, Any] | None = None
    topics: list[str] | None = None
    external_id: str | None = None
    uri: str | None = None
    title_nl: str | None = None
    title_en: str | None = None
    treaty_number: str | None = None
    treaty_type: str | None = None
    status: str | None = None
    in_force: bool | None = None
    date_signed: str | None = None
    date_in_force: str | None = None
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


# ---------------------------------------------------------------------------
# articles
# ---------------------------------------------------------------------------


class ArticleProps(_CommonProps):
    bwb_id: str | None = None
    celex: str | None = None
    article_number: str | None = None
    label: str | None = None
    title: str | None = None
    text: str | None = None
    instrument_citation_title: str | None = None
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
    article_number: str | None = None
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


# ---------------------------------------------------------------------------
# judgments
# ---------------------------------------------------------------------------


class JudgmentParagraphProps(_StrictBase):
    """One paragraph of a judgment (``core.judgments.extract_sections``)."""

    id: str  # ``rov-5.3``, ``kop-5``, ``p-12``: unique in the judgment, for deep links
    number: str | None = None  # as printed, without its closing dot: "5.3"
    kind: Literal["heading", "subheading", "body"]
    text: str


class JudgmentProps(_CommonProps):
    ecli: str | None = None
    source_kind: str | None = None
    meta: dict[str, Any] | None = None
    summary: str | None = None
    text: str | None = None
    judgment_metadata: dict[str, Any] | None = None
    subjects: list[str] | None = None
    paragraphs: list[JudgmentParagraphProps] | None = None
    court: str | None = None
    case_number: str | None = None
    # ``case_number`` split and written as compared (``core.judgments.case_number_keys``)
    case_number_keys: list[str] | None = None
    # the earlier instances the metadata names (``dcterms:relation``)
    related_eclis: list[str] | None = None
    # the conclusion of a judgment, or the judgment of a conclusion (``psi:type`` conclusie)
    conclusion_eclis: list[str] | None = None
    court_code: str | None = None
    tier: str | None = None
    date_eff: str | None = None
    inbound_citation_count: int | None = None
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
    title: str | None = None
    title_source: str | None = None
    closed: bool | None = None
    opened_on: str | None = None
    closed_on: str | None = None
    current_stage: str | None = None
    case_kinds: list[str] | None = None
    stages_present: list[str] | None = None
    stages_complete: bool | None = None
    track_kind: str | None = None
    outcome: str | None = None
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
    kind: str | None = None
    # no source sets it: the Eerste Kamer has no votes here; the API still returns it
    chamber: str | None = None


# ---------------------------------------------------------------------------
# commitments
# ---------------------------------------------------------------------------


class CommitmentProps(_CommonProps):
    external_id: str | None = None
    text: str | None = None
    minister_name: str | None = None
    minister_role: str | None = None
    made_on: str | None = None
    expected_resolution: str | None = None
    status: str | None = None
    activity_number: str | None = None


# ---------------------------------------------------------------------------
# committees
# ---------------------------------------------------------------------------


class CommitteeProps(_CommonProps):
    external_id: str | None = None
    name: str | None = None
    abbreviation: str | None = None
    slug: str | None = None


# ---------------------------------------------------------------------------
# members
# ---------------------------------------------------------------------------


class GovernmentFunctionProps(_StrictBase):
    """A post held in a cabinet (``normalize wikidata``)."""

    function: str | None = (
        None  # "Minister voor Klimaat en Energie", as Wikidata names it
    )
    cabinet: str | None = None  # "kabinet-Rutte IV"
    from_date: str | None = None
    to_date: str | None = None  # null while held
    position_id: str | None = None  # the Wikidata item of the post and of the cabinet
    cabinet_id: str | None = None


class MemberProps(_CommonProps):
    external_id: str | None = None
    name: str | None = None
    party: str | None = None
    faction_memberships: list | None = None
    family_name: str | None = None  # Persoon.Achternaam, without the tussenvoegsel
    birth_date: str | None = None
    wikidata_id: str | None = None
    government_functions: list[GovernmentFunctionProps] | None = None


# ---------------------------------------------------------------------------
# factions
# ---------------------------------------------------------------------------


class FactionProps(_CommonProps):
    external_id: str | None = None
    name: str | None = None
    abbreviation: str | None = None
    aliases: list[str] | None = None
    active_from: str | None = None
    active_until: str | None = None
    seats: int | None = None
    active: bool | None = None


# ---------------------------------------------------------------------------
# topics
# ---------------------------------------------------------------------------


class TopicProps(_CommonProps):
    id: str | None = None
    slug: str | None = None
    name: str | None = None
    description: str | None = None
    tags: list[str] | None = None


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
    # Zaak.GerelateerdNaar: the cases the Kamer relates this one to
    related_cases: list[RelatedCase] | None = None


# ---------------------------------------------------------------------------
# annexes
# ---------------------------------------------------------------------------


class AnnexEntry(_StrictBase):
    index: int | None = None
    name: str | None = None
    description: str | None = None


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
    COLLECTION_TOPICS: TopicProps,
    COLLECTION_CASES: CaseProps,
    COLLECTION_ANNEXES: AnnexProps,
}

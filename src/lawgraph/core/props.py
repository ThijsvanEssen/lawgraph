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
     copies may carry legacy or partial data). Validation runs only when a fresh
     ``Node()`` is constructed in pipeline code.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict


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
    config_id: str | None = None
    topics: list[str] | None = None
    external_id: str | None = None
    uri: str | None = None
    title_nl: str | None = None
    title_en: str | None = None
    verdragsnummer: str | None = None
    treaty_type: str | None = None
    status: str | None = None
    in_force: bool | None = None
    date_signed: str | None = None
    date_in_force: str | None = None
    parties: list[str] | None = None
    article_count: int | None = None
    inbound_citation_count: int | None = None
    date_eff: str | None = None


# ---------------------------------------------------------------------------
# instrument_articles
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


# ---------------------------------------------------------------------------
# instrument_versions
# ---------------------------------------------------------------------------


class InstrumentVersionProps(_CommonProps):
    bwb_id: str | None = None
    valid_from: str | None = None
    valid_until: str | None = None
    current: bool | None = None
    toestand_url: str | None = None


# ---------------------------------------------------------------------------
# instrument_article_versions
# ---------------------------------------------------------------------------


class ArticleVersionProps(_CommonProps):
    bwb_id: str | None = None
    article_number: str | None = None
    valid_from: str | None = None
    valid_until: str | None = None
    current: bool | None = None
    text: str | None = None


# ---------------------------------------------------------------------------
# judgments
# ---------------------------------------------------------------------------


class JudgmentProps(_CommonProps):
    ecli: str | None = None
    raw_xml: str | None = None
    source_kind: str | None = None
    meta: dict[str, Any] | None = None
    summary: str | None = None
    text: str | None = None
    judgment_metadata: dict[str, Any] | None = None
    subjects: list[str] | None = None
    paragraphs: list[dict[str, Any]] | None = None
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
# publications  (TK, TK-dossier docs, Staatsblad, Staatscourant, EersteKamer)
# ---------------------------------------------------------------------------


class PublicationProps(_CommonProps):
    external_id: str | None = None
    # TK-style (old)
    raw: dict[str, Any] | None = None
    procedure_external_id: str | None = None
    onderwerp: str | None = None
    # TK-dossier documents
    dossier_nummer: str | None = None
    dossier_nummers: list[str] | None = None
    zaak_nummers: list[str] | None = None
    volgnummer: str | None = None
    soort: str | None = None
    titel: str | None = None
    title: str | None = None
    datum: str | None = None
    vergaderjaar: str | None = None
    tk_url: str | None = None
    actors: list | None = None
    # Staatsblad / Staatscourant
    identifier: str | None = None
    text: str | None = None
    year: str | None = None
    number: str | None = None
    bwb_id: str | None = None
    bwb_refs: list[str] | None = None
    # EersteKamer
    nummer: str | None = None
    chamber: str | None = None
    kamerstuk_id: str | None = None
    vergadering_id: str | None = None


# ---------------------------------------------------------------------------
# kamerstukdossiers
# ---------------------------------------------------------------------------


class DossierProps(_CommonProps):
    external_id: str | None = None
    nummer: int | None = None
    kamerstuknummer: str | None = None
    toevoeging: str | None = None
    titel: str | None = None
    titel_source: str | None = None
    afgedaan: bool | None = None
    geopend_op: str | None = None
    gesloten_op: str | None = None
    huidige_fase: str | None = None
    zaak_soorten: list[str] | None = None
    stages_present: list[str] | None = None
    traject_kind: str | None = None
    outcome: str | None = None


# ---------------------------------------------------------------------------
# activiteiten
# ---------------------------------------------------------------------------


class ActiviteitProps(_CommonProps):
    external_id: str | None = None
    datum: str | None = None
    agenda_titel: str | None = None
    soort: str | None = None
    commissie_id: str | None = None
    dossier_nummers: list[str] | None = None
    zaak_soorten: list[str] | None = None
    tk_url: str | None = None
    nummer: str | None = None
    video_url: str | None = None


# ---------------------------------------------------------------------------
# stemmingen
# ---------------------------------------------------------------------------


class StemmingProps(_CommonProps):
    # TK stemmingen
    besluit_id: str | None = None
    agendapunt_id: str | None = None
    datum: str | None = None
    onderwerp: str | None = None
    agendapunt_onderwerp: str | None = None
    besluit_tekst: str | None = None
    besluit_volgorde: int | None = None
    vergadering_soort: str | None = None
    dossier_nummers: list[str] | None = None
    zaken: list | None = None
    primary_zaak: dict[str, Any] | None = None
    voor: int | None = None
    tegen: int | None = None
    onthouding: int | None = None
    aangenomen: bool | None = None
    # EK stemmingen
    external_id: str | None = None
    soort: str | None = None
    kamerstuk_id: str | None = None
    vergadering_id: str | None = None
    chamber: str | None = None


# ---------------------------------------------------------------------------
# toezeggingen
# ---------------------------------------------------------------------------


class ToezeggingProps(_CommonProps):
    external_id: str | None = None
    tekst: str | None = None
    minister_naam: str | None = None
    minister_functie: str | None = None
    gedaan_op: str | None = None
    verwachte_afhandeling: str | None = None
    status: str | None = None
    activiteit_nummer: str | None = None
    dossier_id: str | None = None


# ---------------------------------------------------------------------------
# commissies
# ---------------------------------------------------------------------------


class CommissieProps(_CommonProps):
    external_id: str | None = None
    naam: str | None = None
    afkorting: str | None = None
    slug: str | None = None


# ---------------------------------------------------------------------------
# leden
# ---------------------------------------------------------------------------


class LidProps(_CommonProps):
    external_id: str | None = None
    naam: str | None = None
    partij: str | None = None
    actief: bool | None = None
    fractielidmaatschappen: list | None = None


# ---------------------------------------------------------------------------
# fracties
# ---------------------------------------------------------------------------


class FractieProps(_CommonProps):
    external_id: str | None = None
    naam: str | None = None
    afkorting: str | None = None
    aliases: list[str] | None = None
    datum_actief: str | None = None
    datum_inactief: str | None = None
    aantal_zetels: int | None = None
    actief: bool | None = None


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
# procedures (TK Zaken)
# ---------------------------------------------------------------------------


class ProcedureProps(_CommonProps):
    external_id: str | None = None
    raw: dict[str, Any] | None = None
    title: str | None = None
    kamerstuknummer: str | None = None


# ---------------------------------------------------------------------------
# Registry — maps collection name → props validator class
# ---------------------------------------------------------------------------

COLLECTION_SCHEMAS: dict[str, type[_StrictBase]] = {
    "instruments": InstrumentProps,
    "instrument_articles": ArticleProps,
    "instrument_versions": InstrumentVersionProps,
    "instrument_article_versions": ArticleVersionProps,
    "judgments": JudgmentProps,
    "publications": PublicationProps,
    "kamerstukdossiers": DossierProps,
    "activiteiten": ActiviteitProps,
    "stemmingen": StemmingProps,
    "toezeggingen": ToezeggingProps,
    "commissies": CommissieProps,
    "leden": LidProps,
    "fracties": FractieProps,
    "topics": TopicProps,
    "procedures": ProcedureProps,
}

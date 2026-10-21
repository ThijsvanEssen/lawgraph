"""The relation vocabulary: one place that says what every edge type means.

Rules (enforced by ``tests/test_relation_catalogue.py``):

* names are English ``UPPER_SNAKE`` verbs that read as ``SOURCE VERB TARGET``;
* the target type never appears in the name (``REFERS_TO``, not
  ``REFERS_TO_ARTICLE``) — the node the edge points at says what it is;
* an edge type states the pairs of collections it connects (``ends``), each a pair some
  writer makes; ``make_edge_doc`` refuses an edge of any other pair, so a writer that
  produces an edge in the wrong direction fails its own tests
  (``tests/conventions/test_edge_ends.py`` checks every edge is made there).

``RELATIONS`` is the whole vocabulary; ``config.constants`` has one
``RELATION_*`` constant per entry.

Each relation names the model of what its ``meta`` may hold (``RelationSpec.meta``).
``make_edge_doc`` holds every edge to it: a key the model lacks is logged once per
relation, source and key (``unknown_meta_keys``); the tests hold the whole of the meta to
the model (``meta_problems``) and fail on what does not fit.

The tables in ``docs/data-model.md`` between the ``relations`` and the ``edge-meta``
markers, and ``tests/data/relations.json`` (the collections and the relations with their
ends, which the front end is tested against), are generated from this module::

    python -m lawgraph.core.relations
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

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
from lawgraph.core.logging import get_logger
from lawgraph.core.models import COLLECTIONS
from lawgraph.core.props import GovernmentFunctionProps
from lawgraph.core.props_catalogue import field_rows
from lawgraph.core.provenance import Basis, Reason
from lawgraph.core.tk_records.actors import SigningCapacity

logger = get_logger(__name__)

# Concept (English name used in docs and the API) -> collection that stores it.
CONCEPTS: dict[str, str] = {spec.concept: spec.name for spec in COLLECTIONS}
_CONCEPT_OF = {collection: concept for concept, collection in CONCEPTS.items()}


# ── meta ─────────────────────────────────────────────────────────────────────
# What the ``meta`` of an edge of each relation may hold: one model per relation, the keys
# of every writer of it together, since two writers of one edge merge their meta (an MvT
# edge of ``mvt-article-linker`` and ``mvt-section-linker``, a citation between judgments
# of ``judgment-citation-linker`` and ``eurlex-cjeu``). A key is absent where its writer has
# nothing to say.


class _Meta(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)


class _Span(_Meta):
    start: int | None = None
    """Where the reference starts in the text of the source node."""
    end: int | None = None
    """Where it ends."""


class _Parts(_Meta):
    leden: list[str] | None = None
    """The leden the reference names: `["1", "3"]`."""
    onderdelen: list[str] | None = None
    """The onderdelen it names: `["a"]`."""
    aanhef: bool | None = None
    """It names the aanhef of the article."""


class BwbChangeMeta(_Meta):
    """A change the BWB records (``semantic bwb-amendments``)."""

    effective_date: str | None = None
    """The day the version takes effect."""
    article_version: str | None = None
    """The key of the article version the publication made."""
    effect: str | None = None
    """The effect as the BWB writes it: `wijziging`, `nieuwe-regeling`, `vervallen`."""
    source_publication: str | None = None
    """The publication that made the change: `stb-2019-33`."""


class ArticleChangeMeta(BwbChangeMeta):
    """A change of an article: as the BWB records it, or as the text of an amendment
    proposes it (``amendment-article-linker``)."""

    reason: Reason | None = None
    """`amendment_text` (core/provenance.py)."""
    snippet: str | None = None
    """The words of the amendment that name the article."""


class TranspositionPart(_Meta):
    from_: str = Field(alias="from")
    """The part of the old article: `2`, `2 a`, `eerste lid`; empty for the whole."""
    to: str
    """The place in the new law as the source writes it: `2.8.6, 1`, `vervallen (mvt)`."""
    article: str | None = None
    """The number of the new article of the edge (an edge to an article)."""
    leden: list[str] | None = None
    """The leden of it the place names; empty for the whole (an edge to an article)."""
    outcome: str | None = None
    """What the source says of a part it places in no article (an edge to the new law):
    `vervallen`, `niet_overgenomen`, `blijft_in:<law as written>`, `naar:<law as written>`
    (to another law, no article of it named); `gat` for a part that does not hold."""
    via: str | None = None
    """The division of the old law the source names for the old article: `§ 1.2`."""


class TransposedToMeta(_Meta):
    basis: Basis | None = None
    """`transposition_table` (core/provenance.py)."""
    source: str | None = None
    """The paper that gives the table: `blg-1081574`, `kst-34986-3`."""
    parts: list[TranspositionPart] | None = None
    """Each part of the old article with its place in the new law."""
    outcome: str | None = None
    """Of an edge to the new law: the outcome of the old article its parts share, `gat` for
    an old article no source places (`lawgraph succession-gaps`)."""


class BasedOnMeta(_Meta):
    text: str | None = None
    """The reference without list word and law: `16, eerste en zevende lid`."""
    basis_kind: str | None = None
    """`delegates` when the leden named give the power, `mentioned` when the article is only
    named."""


class ImplementingMeasure(_Meta):
    citation: str | None = None
    """How EUR-Lex cites the measure."""
    publication: str | None = None
    """The publication of the measure."""
    title: str | None = None
    """Its title as EUR-Lex gives it."""
    type: str | None = None
    """Its type as EUR-Lex gives it."""


class ImplementsMeta(_Meta):
    bases: list[str] | None = None
    """The implementation sources: `national_implementing_measure`, `considerans`."""
    publications: list[str] | None = None
    """The publications EUR-Lex lists as national implementing measures."""
    measures: list[ImplementingMeasure] | None = None
    """Those measures as EUR-Lex lists them."""


class LegislatedInMeta(_Meta):
    dossier_number: str | None = None
    """The number of the dossier."""


class PublishedInMeta(_Meta):
    description: str | None = None
    """What it publishes, as the register writes it."""


class TextPlace(_Meta):
    part: str
    """`title`, `text` or `footnote`."""
    start: int
    """Where the citation starts in that part."""
    end: int
    """Where it ends."""
    section_id: str | None = None
    """The innermost section of the text it stands in."""
    footnote: str | None = None
    """The footnote as printed."""
    footnote_id: str | None = None
    """The id of the footnote."""


class Mention(_Parts):
    paragraph_id: str
    """The paragraph of the judgment."""
    paragraph_number: str | None = None
    """Its number as printed."""
    start: int
    """Where the mention starts in the paragraph (or the footnote)."""
    end: int
    """Where it ends."""
    raw_match: str
    """The mention as written."""
    snippet: str
    """The words around it."""
    snippet_start: int | None = None
    """Where the snippet starts in the paragraph."""
    confidence: float
    """How sure the reading is."""
    qualifier: str | None = None
    """The leden or onderdelen as written: `derde lid`."""
    footnote: str | None = None
    """The label of the footnote that cites it."""


class RefersToMeta(_Span, _Parts):
    """A citation, with the fields of each way one is read."""

    reason: Reason | None = None
    """What the citation names or how it was read (core/provenance.py)."""
    text: str | None = None
    """The reference as written (`bwb-article-references`, `staatsblad-law-references`,
    `tk-cited-papers`)."""
    reference_kind: str | None = None
    """`intref` or `extref`, as the BWB XML writes the link."""
    footnote: int | None = None
    """The footnote of the citing article it stands in, its place in `footnotes`
    (`bwb-article-references`); it then has no `start` and `end` in the text."""
    semantic_pattern: str | None = None
    """The pattern that typed the reference (`semantic_type`)."""
    semantic_confidence: float | None = None
    """How sure that typing is."""
    raw_match: str | None = None
    """The citation as written."""
    snippet: str | None = None
    """The words around it."""
    qualifier: str | None = None
    """The leden or onderdelen as written: `derde lid`."""
    place: TextPlace | None = None
    """Where the citation stands in the paper; null for one over two parts."""
    mention_count: int | None = None
    """How many places of the judgment cite it."""
    mentions: list[Mention] | None = None
    """The first of those places."""
    paragraphs: list[str] | None = None
    """The numbers of the paragraphs that cite it, each once."""
    cited_ecli: str | None = None
    """The ECLI the judgment cites."""
    cited_appno: str | None = None
    """The application number of the ECHR decision it cites."""
    basis: Basis | None = None
    """`subject` (core/provenance.py)."""


class MvtSection(_Meta):
    section_anchor: str
    """The section of the memorandum."""
    heading: str
    """Its heading."""
    char_start: int
    """Where it starts in the text of the memorandum."""
    char_end: int
    """Where it ends."""
    match_type: str
    """How the section names the article: `heading_target`, `body_named_law`,
    `own_number`, `inferred_law`, `bill_part` or `amendment` (`docs/pipelines.md`)."""
    changed: bool
    """The dossier changed the article, or established it as an article of the law it
    made, which corroborates the match."""
    confidence: float
    """How sure the match is."""
    explanation: str
    """What the match rests on, in Dutch."""


class ExplainsMeta(_Meta):
    """The surest section of an MvT that is about the article, and every section."""

    section_anchor: str | None = None
    """The `id` of the surest section (`props.sections` of the Document); the keys below
    up to `sections` are that section's."""
    char_start: int | None = None
    """Where it starts in `props.text` of the Document."""
    char_end: int | None = None
    """Where it ends."""
    heading: str | None = None
    """Its heading."""
    sections: list[MvtSection] | None = None
    """Every section about the article, in the order of the memorandum."""


class JudgmentLinkMeta(_Meta):
    """A judgment tied to another of its case (`APPEAL_OF`, `REFERRED_BY`, `ADVISES_ON`)."""

    basis: Basis | None = None
    """What names the other (core/provenance.py)."""
    procedure_type: str | None = None
    """The procedure as the source writes it: `Hoger beroep`, `Cassatie`."""


class ContinuesMeta(JudgmentLinkMeta):
    reason: Reason | None = None
    """`verplaatst`: an activity replaced a moved one."""


class AnswersMeta(_Meta):
    basis: Basis | None = None
    """What names the other (core/provenance.py)."""
    text: str | None = None
    """The subject, line or footnote that names the motion."""
    reference: str | None = None
    """The reference as written."""


class SameAsMeta(_Meta):
    basis: Basis | None = None
    """What makes the two the same (core/provenance.py)."""


class ScopedByMeta(_Meta):
    scope_type: str | None = None
    """`fixed` or `discretionary`."""


class MadeInMeta(_Meta):
    reason: Reason | None = None
    """`ingediend`: a motion submitted in the debate."""


class CommitteePeriod(_Meta):
    from_date: str | None = None
    """The first day."""
    to_date: str | None = None
    """The last day; absent while it lasts."""
    role: str | None = None
    """The role as the source writes it."""
    substitute: bool | None = None
    """`true` for a substitute."""


class MemberOfMeta(CommitteePeriod):
    """A seat in a committee or faction: of the Tweede Kamer the official period, of the
    Eerste Kamer the period observed on its site."""

    periods: list[CommitteePeriod] | None = None
    """Every seat in the committee, oldest first."""
    record_ids: list[str] | None = None
    """The `FractieZetelPersoon` records of the faction seat."""
    observed_from: str | None = None
    """The first day the Eerste Kamer site showed the seat."""
    observed_until: str | None = None
    """The day it no longer did; null while it does."""


class ServedInMeta(_Meta):
    posts: list[GovernmentFunctionProps] | None = None
    """The posts held in the cabinet, as in the member's `government_functions`."""


class AuthoredMeta(_Meta):
    role: str | None = None
    """How: as the source writes it (`Eerste ondertekenaar`), or `toezegger`."""
    function: str | None = None
    """As what (`Functie`)."""
    capacity: SigningCapacity | None = None
    """In which capacity."""


class PairSide(_Meta):
    document: str | None = Field(default=None, alias="paper")
    """The document of its own kind; null when the graph has none."""
    kind: str | None = None
    """The kind of the paper."""
    dossier_number: str | None = None
    """Its dossier."""
    dossier_suffix: str | None = None
    """The suffix of that dossier."""
    sequence: int | None = None
    """Its number in the dossier."""


class CasePair(_Meta):
    from_: PairSide = Field(alias="from")
    """The paper of the case of this dossier."""
    to: PairSide
    """The paper of the case of the other."""


class RelatedToMeta(_Meta):
    basis: Basis | None = None
    """`summary_text` (core/provenance.py)."""
    text: str | None = None
    """The sentence of the summary that names the other."""
    cases: int | None = None
    """How many pairs of cases relate the dossiers."""
    case_kinds: str | list[str] | None = None
    """What the cases are: of two cases one (`Brief regering → Motie`), of two dossiers
    each."""
    pairs: list[CasePair] | None = None
    """The papers of the newest pairs."""


class RevisesMeta(_Meta):
    rule: str | None = None
    """`begrotingswijziging`, `slotwet` or `vervanging`."""


class AccompaniesMeta(_Meta):
    nota: str | None = None
    """The Voorjaarsnota, Najaarsnota or Miljoenennota."""


class VotedMeta(_Meta):
    choice: str | None = None
    """The choice as the source writes it: `Voor`, `Tegen`."""
    seats: int | None = None
    """The seats the vote counts."""
    record_ids: list[str] | None = None
    """The `Stemming` records it is made of."""


@dataclass(frozen=True)
class RelationSpec:
    name: str
    ends: tuple[
        tuple[str, str], ...
    ]  # (collection it starts in, collection it ends in)
    description: str
    meta: type[_Meta] | None = None  # what ``meta`` may hold; None: nothing

    @property
    def sources(self) -> tuple[str, ...]:
        """The collections an edge may start in, in the order of ``ends``."""
        return tuple(dict.fromkeys(source for source, _ in self.ends))

    @property
    def targets(self) -> tuple[str, ...]:
        """The collections an edge may end in, in the order of ``ends``."""
        return tuple(dict.fromkeys(target for _, target in self.ends))


_I = COLLECTION_INSTRUMENTS
_IV = COLLECTION_INSTRUMENT_VERSIONS
_A = COLLECTION_ARTICLES
_AV = COLLECTION_ARTICLE_VERSIONS
_ANNEX = COLLECTION_ANNEXES
_J = COLLECTION_JUDGMENTS
_DOSSIER = COLLECTION_DOSSIERS
_CASE = COLLECTION_CASES
_DOC = COLLECTION_DOCUMENTS
_ACT = COLLECTION_ACTIVITIES
_DEC = COLLECTION_DECISIONS
_COMMIT = COLLECTION_COMMITMENTS
_MEMBER = COLLECTION_MEMBERS
_FACTION = COLLECTION_FACTIONS
_CABINET = COLLECTION_CABINETS
_COMMITTEE = COLLECTION_COMMITTEES

RELATIONS: tuple[RelationSpec, ...] = (
    # ── structure ────────────────────────────────────────────────────────────
    RelationSpec(
        "PART_OF",
        (
            (_A, _I),
            (_ANNEX, _I),
            (_DOC, _CASE),
            (_DOC, _DOSSIER),
            (_CASE, _DOSSIER),
            (_I, _I),
        ),
        "Containment. Article/Annex → Instrument; Document → Case or Dossier; "
        "Case → Dossier; a treaty → the treaty it belongs to, as the Verdragenbank registers "
        "it (a Protocol → its Convention, `Moederverdrag`).",
    ),
    RelationSpec(
        "VERSION_OF",
        (
            (_IV, _I),
            (_AV, _A),
        ),
        "A dated version of an instrument or article. An article keeps one "
        "identity across versions (BWB `stam-id`); each version has valid_from / "
        "valid_until.",
    ),
    # ── legislation ──────────────────────────────────────────────────────────
    RelationSpec(
        "ESTABLISHES",
        ((_I, _A),),
        "A publication enacts a new regulation and so sets its articles: the BWB effect "
        "`nieuwe-regeling` of the article version it made (effective date and version in "
        "`meta`). No change of existing law: a regulation names its enacting publication "
        "in `props.enacted_publication` as well.",
        meta=BwbChangeMeta,
    ),
    RelationSpec(
        "AMENDS",
        (
            (_I, _A),
            (_DOC, _I),
            (_DOC, _A),
        ),
        "An instrument changes existing text (effective date and version in `meta`). "
        "A bill (Document) proposing the change carries status `voorgesteld`; a paper of "
        "the bill that made an instrument (`LEGISLATED_IN` its dossier) never amends it.",
        meta=ArticleChangeMeta,
    ),
    RelationSpec(
        "INTRODUCES",
        (
            (_I, _A),
            (_DOC, _A),
        ),
        "An instrument adds a new article; a bill proposing it is `voorgesteld`.",
        meta=ArticleChangeMeta,
    ),
    RelationSpec(
        "REPEALS",
        (
            (_I, _A),
            (_DOC, _A),
        ),
        "An instrument withdraws an article; a bill proposing it is `voorgesteld`.",
        meta=ArticleChangeMeta,
    ),
    RelationSpec(
        "TRANSPOSED_TO",
        ((_A, _A), (_A, _I)),
        "An article of the old law → the article of the new law that takes its place in a "
        "recodification (of Dutch law, or a codification or recast of EU law), as an "
        "official source gives it (`meta.basis`; `meta.source` the identifier of that "
        "source: `blg-1081574`, `kst-34986-3`, the CELEX number of the EU act: "
        "`32017R1001`). `meta.parts` pairs each "
        "part of the old article (`from`: `2`, `2 a`, `eerste lid`, empty for the whole; "
        "`via` the division of the old law the source names: `§ 1.2`) "
        "with the place in the new law as the source writes it (`to`: `2.8.6, 1`, "
        "`8.2.26, vierde lid`), read: the number of the new article of the edge "
        '(`article`) and the leden it names (`leden`: `["1"]`; empty for the whole). The '
        "article of another law the source names (`afdeling 3.5 Awb`) is one too. An "
        "article of the old law → the new law (Instrument): what the source says of the "
        "parts it places in no article (`parts[].outcome`: `vervallen`, "
        "`niet_overgenomen`, `blijft_in:<law>`, `naar:<law>`), and of an old article no "
        "source places, its parts as the source writes them (`meta.outcome` `gat`). A row "
        "the source gives that the text of the laws does not hold is no edge to an article: "
        "`lawgraph succession-gaps` lists it. In a table of an old regulation, the column "
        "of a law beside the regulations under it (`Artikel Omgevingswet` beside `Artikel "
        "AMvB`, Stb. 2020, 400) names their delegation basis, no place: no edge (the basis "
        "is the new regulation's `BASED_ON`).",
        meta=TransposedToMeta,
    ),
    RelationSpec(
        "BASED_ON",
        ((_I, _A),),
        "The legal basis (delegation basis) an instrument is issued under: "
        "'Gelet op artikel …' in the preamble; a range ('artikelen 26 tot en met 30') to "
        "each article in force in it. `meta.text` is the reference without list word and "
        "law ('16, eerste en zevende lid'); `meta.basis_kind` `delegates` when the leden "
        "named give the power (a delegation formula, 'bij besluit', 'kan regels stellen'), "
        "`mentioned` when the article is only named (Awb 3:4 by a policy rule).",
        meta=BasedOnMeta,
    ),
    RelationSpec(
        "IMPLEMENTS",
        ((_I, _I),),
        "A national instrument implements an EU act, by an implementation source "
        "(`meta.bases`): a publication EUR-Lex lists as a national implementing measure of "
        "the act, and the regulations it enacted or changed (`national_implementing_measure`, "
        "`meta.publications`, and `meta.measures`: each with `citation`, and `title` and "
        "`type` as EUR-Lex gives them), or a regulation whose considerans says it implements "
        "the act (`considerans`). Not per article: no source names the implementing article.",
        meta=ImplementsMeta,
    ),
    RelationSpec(
        "LEGISLATED_IN",
        ((_I, _DOSSIER),),
        "The parliamentary dossier in which an instrument was legislated (the "
        "`dossierref` of the BWB or of the law in the Staatsblad), or in which a treaty "
        "was approved (the Verdragenbank's `Kamerstukken`).",
        meta=LegislatedInMeta,
    ),
    RelationSpec(
        "PUBLISHED_IN",
        ((_I, _I),),
        "A treaty → a Tractatenblad that publishes it or something about it, as the "
        "Verdragenbank registers it: its text, its approval, its entry into force, its "
        "parties (`meta.description`, as the register writes it).",
        meta=PublishedInMeta,
    ),
    # ── references and explanation ───────────────────────────────────────────
    RelationSpec(
        "REFERS_TO",
        (
            (_A, _A),
            (_A, _I),
            (_DOC, _A),
            (_DOC, _I),
            (_DOC, _DOC),
            (_J, _A),
            (_J, _I),
            (_J, _J),
            (_I, _A),
            (_I, _I),
        ),
        "A text refers to an article, instrument, judgment or Kamerstuk: the reference is in "
        "the text, never only in metadata (a judgment's earlier instance or conclusion is "
        "`APPEAL_OF` or `ADVISES_ON`), and two judgments of one case tied by `APPEAL_OF`, "
        "`CONTINUES`, `REFERRED_BY`, `ADVISES_ON` or `ANSWERS` have that edge only. The "
        "source node says who refers; article → "
        "article edges also carry a `semantic_type`. From an instrument: a regulation "
        "whose text names the CELEX number of an EU act it does not `IMPLEMENTS`, or an EU "
        "act → an article or act its text names. Judgment → instrument: a law the "
        "conclusion of an ECHR judgment names by its BWB id. Document → "
        'document: its subject names the paper by dossier and number, "(Kamerstuk '
        '36945-XIV-1)" (`meta.basis` `subject`, `meta.text` as written), unless it `ANSWERS` '
        "it.",
        meta=RefersToMeta,
    ),
    RelationSpec(
        "EXPLAINS",
        (
            (_DOC, _AV),
            (_DOC, _A),
            (_DOC, _I),
        ),
        "A document (MvT, NvT) explains the article version or instrument it "
        "introduced or changed. Written per dossier: every MvT and NvT of a "
        "dossier explains everything its law changed; an MvT edge carries "
        "`meta.section_anchor` when one of its sections is about that article.",
        meta=ExplainsMeta,
    ),
    RelationSpec(
        "APPEAL_OF",
        ((_J, _J),),
        "An appeal or cassation judgment → the judgment it appeals: an earlier instance "
        "its metadata names (`meta.basis` `formal_relation`), else the decision its text "
        "says it appeals, by date and case number (`appeal_text`).",
        meta=JudgmentLinkMeta,
    ),
    RelationSpec(
        "CONTINUES",
        (
            (_J, _J),
            (_ACT, _ACT),
        ),
        "A judgment → an earlier one of the same court in the same case (an interim "
        "judgment followed by the final one): an earlier instance its metadata names that "
        "shares its court and case number. An activity → the moved activity it replaced "
        "(`Activiteit.VervangenDoor`; `meta.reason` `verplaatst`).",
        meta=ContinuesMeta,
    ),
    RelationSpec(
        "REFERRED_BY",
        ((_J, _J),),
        "A decision after referral (verwijzing) → the ruling of the Hoge Raad that set "
        "aside the earlier decision and sent the case to it: an earlier instance its "
        "metadata names that is a Hoge Raad ruling (not a preliminary ruling).",
        meta=JudgmentLinkMeta,
    ),
    RelationSpec(
        "ADVISES_ON",
        ((_J, _J),),
        "The conclusion of an advocate-general (Parket bij de Hoge Raad, or of the court "
        "itself) → the judgment in its case, one way only: the formal relation of either, "
        "when the side it calls the conclusion is one (`meta.basis` `formal_relation`), "
        "else a case number the two share (`case_number`).",
        meta=JudgmentLinkMeta,
    ),
    RelationSpec(
        "ANSWERS",
        (
            (_J, _J),
            (_DOC, _COMMIT),
            (_DOC, _DOC),
        ),
        "A preliminary ruling (prejudiciële beslissing) → the decision that asked its "
        "questions: the earlier instance its metadata names (`meta.basis` "
        "`formal_relation`), else the ECLI or the case number and date its text names "
        "(`referral_text`). A letter → the commitment it fulfils "
        "(`Toezegging.KamerbriefNakoming`). A letter of the government → a motion its "
        'subject names by dossier and number, "Uitvoering van de motie … (Kamerstuk '
        '25424-795)" (`meta.basis` `subject`, `meta.text` the whole subject, '
        "`meta.reference` the reference as written), or its text or a footnote names: "
        '"Kamerstuk 36 764, nr. 28", "de motie-Kathmann (36764, nr. 31)" (`meta.basis` '
        "`text` or `footnote`, `meta.text` the line or footnote, confidence 0.9).",
        meta=AnswersMeta,
    ),
    RelationSpec(
        "SAME_AS",
        (
            (_J, _J),
            (_I, _I),
            (_DOC, _I),
            (_MEMBER, _MEMBER),
        ),
        "A publication of a decision → the publication of the same decision that replaces "
        "it (an old arrest published again under a new ECLI): the ECLI its metadata names "
        "as `dcterms:isReplacedBy`. The lists show the decision once, by the one kept. "
        "The BWB text of a treaty (`BWBV…`) → its Verdragenbank treaty, by the treaty "
        "number the text names (`wetgeving@verdragnummer`). A paper of the Staatsblad or "
        "the Staatscourant → the publication of the BWB of the same official id "
        "(`stb-2019-33`, `stcrt-2020-12345`), by their keys. A bare `Persoon` of the Tweede "
        "Kamer → the member with a role who is the same person: the same birth date, surname "
        "and initials (`tk-person-duplicates`).",
        meta=SameAsMeta,
    ),
    RelationSpec(
        "SCOPED_BY",
        ((_A, _ANNEX),),
        "An article whose scope is defined by an annex.",
        meta=ScopedByMeta,
    ),
    # ── parliament ───────────────────────────────────────────────────────────
    RelationSpec(
        "ABOUT",
        (
            (_ACT, _CASE),
            (_ACT, _DOSSIER),
            (_DEC, _CASE),
            (_DEC, _DOSSIER),
            (_DEC, _DOC),
            (_COMMIT, _DOSSIER),
        ),
        "The subject of an activity, decision or commitment: Activity/Decision → "
        "Case and Dossier; Commitment → Dossier. A vote of the Eerste Kamer on a motion → "
        "the motion, its Kamerstuk with that letter (`Kamerstuk I 37020, M`): a paper of the "
        "Eerste Kamer has no case, where a decision of the Tweede Kamer is about the case of "
        "its motion.",
    ),
    RelationSpec(
        "LED_BY",
        (
            (_ACT, _COMMITTEE),
            (_CASE, _COMMITTEE),
        ),
        "The lead committee (`voortouwcommissie`) of an activity or case; absent for "
        "plenary.",
    ),
    RelationSpec(
        "MADE_IN",
        (
            (_COMMIT, _ACT),
            (_DOC, _ACT),
            (_DEC, _ACT),
        ),
        "The activity in which a commitment (toezegging) was made, or a decision taken (the "
        "activity of its agenda item: `Agendapunt.Activiteit`), or of which a document is the "
        "record (a stenogram of its debate: `Document.Activiteit`), or a motion submitted: "
        "the debate held on the day its case started that has the case on its agenda and "
        "took no decision on it (`meta.reason` `ingediend`).",
        meta=MadeInMeta,
    ),
    RelationSpec(
        "MEMBER_OF",
        (
            (_MEMBER, _COMMITTEE),
            (_MEMBER, _FACTION),
        ),
        "Membership of a committee or faction, with from/to dates and role.",
        meta=MemberOfMeta,
    ),
    RelationSpec(
        "SERVED_IN",
        ((_MEMBER, _CABINET),),
        "The posts a member held in a cabinet, one edge per member and cabinet, "
        "`meta.posts` as in the member's `government_functions`.",
        meta=ServedInMeta,
    ),
    RelationSpec(
        "AUTHORED",
        (
            (_MEMBER, _DOC),
            (_MEMBER, _CASE),
            (_MEMBER, _COMMIT),
        ),
        "A person signed or submitted a document or case; `role` says how "
        "(first signatory, co-signatory, …), `function` as what (`Functie`) and "
        "`capacity` in which capacity (`kamerlid`, `bewindspersoon`, `overig`). A "
        "bewindspersoon made a commitment (`role` `toezegger`).",
        meta=AuthoredMeta,
    ),
    RelationSpec(
        "RELATED_TO",
        (
            (_CASE, _CASE),
            (_DOSSIER, _DOSSIER),
            (_J, _J),
        ),
        "Case → case: the Kamer relates the two (`Zaak.GerelateerdNaar`, `meta.case_kinds`). "
        "Dossier → dossier: the Kamer relates a case of this dossier to a case of the other "
        "(`Zaak.GerelateerdNaar`), mostly a letter of the government to the motion it "
        "answers; `meta.cases` counts the pairs of cases, `meta.case_kinds` names them, "
        "`meta.pairs` gives the papers of the 5 newest pairs (`{kinds, from, to}`, a side "
        "`{case, paper, kind, dossier_number, dossier_suffix, sequence, date}`). "
        'Judgment → judgment: its summary names the other as a connected case, "Samenhang '
        'met 24/03860 E", "Zie ook: ECLI:NL:GHDHA:2025:1539" (`meta.basis` '
        "`summary_text`, `meta.text` the sentence as written); only on an exact match of the "
        "ECLI, or of the case number among the judgments of the same court (the Hoge Raad's "
        "type letter is not part of the comparison).",
        meta=RelatedToMeta,
    ),
    RelationSpec(
        "REVISES",
        (
            (_DOSSIER, _DOSSIER),
            (_DOC, _DOC),
        ),
        "A supplementary budget or a slotwet revises the budget of its chapter and year "
        "(`meta.rule`: `begrotingswijziging` or `slotwet`; Dossier → Dossier); an amended "
        'amendment or motion replaces the one it names, "ter vervanging van nr. 21" '
        "(`meta.rule` `vervanging`, `Zaak.VervangenVanuit`; Document → Document).",
        meta=RevisesMeta,
    ),
    RelationSpec(
        "ACCOMPANIES",
        (
            (_DOSSIER, _DOSSIER),
            (_DOC, _DOC),
        ),
        "A budget change is submitted with the Voorjaarsnota, Najaarsnota or "
        "Miljoenennota (`meta.nota`) that its title names (Dossier → Dossier); an "
        "attachment is sent with its letter (Document → Document: `BijlageDocument`).",
        meta=AccompaniesMeta,
    ),
    RelationSpec(
        "SECOND_READING_OF",
        ((_DOSSIER, _DOSSIER),),
        "A change in the Grondwet in its second reading → the dossier of its first reading, "
        "to whose papers its memorandum refers for the explanation (Kamerstukken 35 418).",
    ),
    RelationSpec(
        "VOTED",
        (
            (_MEMBER, _DEC),
            (_FACTION, _DEC),
        ),
        "A vote on a decision: per member for roll-call votes, per faction "
        "otherwise (`choice`, `seats`).",
        meta=VotedMeta,
    ),
)

RELATION_NAMES: frozenset[str] = frozenset(r.name for r in RELATIONS)
BY_NAME: dict[str, RelationSpec] = {r.name: r for r in RELATIONS}
_ENDS: frozenset[tuple[str, str, str]] = frozenset(
    (r.name, source, target) for r in RELATIONS for source, target in r.ends
)


def without_unknown_relations[T](
    items: Iterable[T], relation_of: Callable[[T], object]
) -> list[T]:
    """*items* without those whose relation (*relation_of*; None is none) the catalogue
    lacks, each such relation logged once: the edges a later release wrote, read by this
    one after a rollback, are left out, not an error of the request."""
    kept: list[T] = []
    unknown: set[str] = set()
    for item in items:
        relation = relation_of(item)
        if relation is None or relation in RELATION_NAMES:
            kept.append(item)
        else:
            unknown.add(str(relation))
    if unknown:
        logger.warning(
            "Edges of a relation not in the catalogue left out: %s", sorted(unknown)
        )
    return kept


def allows(relation: str, source: str, target: str) -> bool:
    """Whether the catalogue has *relation* from collection *source* to *target*."""
    return (relation, source, target) in _ENDS


# relation -> the keys its ``meta`` may hold at the top, as stored: what ``make_edge_doc``
# checks and what the edge upsert keeps of the stored meta (``bulk_insert_or_update_edges``)
META_KEYS: dict[str, frozenset[str]] = {
    r.name: frozenset(
        field.alias or name
        for name, field in (r.meta.model_fields.items() if r.meta else ())
    )
    for r in RELATIONS
}


def unknown_meta_keys(relation: str, meta: Mapping[str, Any]) -> list[str]:
    """The keys at the top of *meta* the model of *relation* lacks: a set difference, cheap
    enough for every edge a run makes."""
    allowed = META_KEYS.get(relation)
    if allowed is None or meta.keys() <= allowed:
        return []
    return sorted(meta.keys() - allowed)


def meta_problems(relation: str, meta: Mapping[str, Any]) -> list[str]:
    """What of *meta* the model of *relation* does not allow, all the way down (strict
    validation): ``unknown key x`` or ``x[].y: <pydantic error type>``."""
    spec = BY_NAME.get(relation)
    if spec is None or not meta:
        return []
    if spec.meta is None:
        return [f"unknown key {key}" for key in sorted(meta)]
    try:
        spec.meta.model_validate(dict(meta), strict=True)
    except ValidationError as error:
        found = set()
        for item in error.errors():
            where = "".join(
                f".{part}" if isinstance(part, str) else "[]" for part in item["loc"]
            ).lstrip(".")
            found.add(
                f"unknown key {where}"
                if item["type"] == "extra_forbidden"
                else f"{where}: {item['type']}"
            )
        return sorted(found)
    return []


def concept(collection: str) -> str:
    """Concept name for a collection (``procedures`` → ``Case``)."""
    return _CONCEPT_OF.get(collection, collection)


def _markers(block: str) -> tuple[str, str]:
    return (
        f"<!-- {block}:begin (generated: python -m lawgraph.core.relations) -->",
        f"<!-- {block}:end -->",
    )


def render_tables() -> str:
    """Markdown tables of the node types and the relations (no headings)."""
    lines = [
        "| Node type | Collection |",
        "|-----------|-----------|",
    ]
    lines += [f"| {c} | `{col}` |" for c, col in CONCEPTS.items()]
    lines += [
        "",
        "| Relation | From → To | Meaning |",
        "|----------|-----------|---------|",
    ]
    for r in RELATIONS:
        ends = ", ".join(f"{concept(a)} → {concept(b)}" for a, b in r.ends)
        lines.append(f"| `{r.name}` | {ends} | {r.description} |")
    return "\n".join(lines) + "\n"


def render_meta_table() -> str:
    """The Markdown table of the keys of ``meta`` per relation, and the relations without."""
    lines = [
        "| Relation | Key | Type | Meaning |",
        "|----------|-----|------|---------|",
    ]
    names = {Basis: "Basis", Reason: "Reason"}  # their values: the provenance table
    for r in RELATIONS:
        if r.meta is not None:
            for i, row in enumerate(field_rows(r.meta, set(), names=names)):
                lines.append(f"| {f'`{r.name}`' if i == 0 else ''} {row}")
    bare = ", ".join(f"`{r.name}`" for r in RELATIONS if r.meta is None)
    return "\n".join([*lines, "", f"Without meta: {bare}."]) + "\n"


_RENDER = {"relations": render_tables, "edge-meta": render_meta_table}


def replace_block(document: str, block: str = "relations") -> str:
    """Return *document* with the generated *block* between its markers refreshed."""
    begin, end = _markers(block)
    head, _, rest = document.partition(begin)
    _, _, tail = rest.partition(end)
    return f"{head}{begin}\n\n{_RENDER[block]()}\n{end}{tail}"


def block_of(document: str, block: str = "relations") -> str:
    """The generated *block* currently in *document* (markers excluded)."""
    begin, end = _markers(block)
    _, _, rest = document.partition(begin)
    body, _, _ = rest.partition(end)
    return body.strip() + "\n"


def render_json() -> str:
    """``relations.json``: the collections, and each relation with the pairs of collections
    it connects (``ends``) and the collections it may start and end in, in the order of the
    catalogue."""
    contract = {
        "about": "Generated by python -m lawgraph.core.relations: the collections of the "
        "nodes and the relations with their ends, as the API types them.",
        "collections": list(CONCEPTS.values()),
        "relations": [
            {
                "name": r.name,
                "sources": list(r.sources),
                "targets": list(r.targets),
                "ends": [list(end) for end in r.ends],
            }
            for r in RELATIONS
        ],
    }
    return json.dumps(contract, indent=2) + "\n"


if __name__ == "__main__":
    import pathlib

    root = pathlib.Path(__file__).resolve().parents[3]
    path = root / "docs" / "data-model.md"
    path.write_text(replace_block(replace_block(path.read_text()), "edge-meta"))
    root.joinpath("tests", "data", "relations.json").write_text(render_json())

"""Typed props schemas for every node collection (``models.COLLECTIONS``).

Each node collection has a corresponding Pydantic model with ``extra="forbid"``.
This catches typos in field names (e.g. ``bwbr_id`` instead of ``bwb_id``) and
undeclared fields at Node construction time.

Rules for maintainers:
  1. All fields are Optional — props are merged across pipeline runs; no single
     pipeline writes every field on every pass.
  2. ``extra="forbid"`` is intentional — unknown field names raise ValidationError.
     If you legitimately need a new field, add it to the schema *first*.
  3. ``from_document()`` bypasses validation (DB reads may carry partial data).
     Validation runs only when a fresh ``Node()`` is constructed in pipeline code.
     A write that skips validation (a skeleton, a bulk or SQL update) still sets only the
     fields named here (``models.require_named_props``).
  4. Every field says what it holds in the docstring under it: the props tables of
     ``docs/data-model.md`` are made from them (``python -m lawgraph.core.props_catalogue``).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class _StrictBase(BaseModel):
    model_config = ConfigDict(extra="forbid", use_attribute_docstrings=True)


class _CommonProps(_StrictBase):
    """Fields present in nearly every collection's props."""

    display_name: str | None = None
    """The name to show; a long name is cut with an ellipsis (``core/display.shorten``),
    the full title stays in `title`."""
    source: str | None = None
    """The source the node was read from: `bwb`, `eurlex`, `rechtspraak`, `echr`, `cjeu`,
    `tk`, `eerstekamer`, `verdragenbank`, `rijksoverheid`, ..."""
    stub: bool | None = None
    """`true` for a placeholder made because something referred to it before its own source
    was loaded."""


# ---------------------------------------------------------------------------
# instruments
# ---------------------------------------------------------------------------


class LegalAreaProps(_StrictBase):
    """A legal area of a BWB regulation (WTI ``rechtsgebied``), with its TOOI concepts."""

    main: str
    """The main area as the WTI names it ("Staats- en bestuursrecht")."""
    main_id: str | None = None
    """The id of its TOOI concept (`scw_bwb_rechtsgebieden`)."""
    main_uri: str | None = None
    """The URI of that concept."""
    main_slug: str | None = None
    """Its slug, unique in the list."""
    specific: str | None = None
    """The specific area within it ("Bestuursrecht")."""
    specific_id: str | None = None
    """The id of its TOOI concept."""
    specific_uri: str | None = None
    """The URI of that concept."""
    specific_slug: str | None = None
    """Its slug, unique in the list."""


class PolicyDomainProps(_StrictBase):
    """A government theme of a BWB regulation (WTI ``overheidsdomein``), with its TOOI
    concept."""

    label: str
    """The theme as the WTI names it ("Overheid, bestuur en koninkrijk")."""
    id: str | None = None
    """The id of its TOOI concept (`scw_bwb_themas`)."""
    uri: str | None = None
    """The URI of that concept."""
    slug: str | None = None
    """Its slug, unique in the list."""


class TreatyPublicationProps(_StrictBase):
    """A Tractatenblad of a treaty (``core.verdragenbank_xml``)."""

    official_id: str | None = None
    """Its id at officielebekendmakingen.nl: `trb-1951-154`."""
    text: str
    """As the register writes it: "1951, 154"."""
    description: str | None = None
    """What it publishes: "goedkeuring, inwerkingtreding"."""


class TreatyPartyProps(_StrictBase):
    """A state party to a treaty, with its dates as the register gives them."""

    name: str
    """The state."""
    signed: str | None = None
    """`DatumOndertekenning`."""
    ratified: str | None = None
    """`DatumRatificatie`."""
    consent: str | None = None
    """`TypeInstemming`: `R`, `T` (toetreding), `A`, ..."""
    provisional: str | None = None
    """`DatumVoorlopigeToepassing`."""
    in_force: str | None = None
    """`DatumInwerkingtreding`."""
    retroactive: str | None = None
    """`DatumTerugwerkendeKracht`."""
    denounced: str | None = None
    """`DatumOpzegging`."""
    terminated: str | None = None
    """`DatumBuitenwerkingtreding`."""
    reservation: bool | None = None
    """`IsVoorbehoud`: it made a reservation."""
    objection: bool | None = None
    """`IsBezwaar`: it made an objection."""


class TreatyKingdomPartProps(_StrictBase):
    """A part of the Kingdom a treaty applies to, with its dates as the register gives
    them."""

    part: str | None = None
    """"Nederland (in Europa)", "Aruba"."""
    provisional: str | None = None
    """`DatumVoorlopigeToepassing`."""
    in_force: str | None = None
    """`DatumInwerkingtreding`."""
    retroactive: str | None = None
    """`DatumTerugwerkendeKracht`."""
    terminated: str | None = None
    """`DatumBuitenwerkingtreding`."""


class TreatyDossierProps(_StrictBase):
    """A dossier of the approval of a treaty, as the register names it."""

    dossier: str
    """The dossier number."""
    rijks_number: str | None = None
    """The number of a rijkswet (`R2188`), as the register writes it."""
    sub_number: str | None = None
    """The sub-number, as the register writes it."""


class RelatedTreatyProps(_StrictBase):
    """A treaty the register relates to a treaty (parent or child)."""

    id: str | None = None
    """The Verdragenbank id: `005132`."""
    title: str | None = None
    """Its title."""
    date: str | None = None
    """Its date, as the register gives it."""
    place: str | None = None
    """Its place, as the register gives it."""


class InstrumentProps(_CommonProps):
    legal_areas: list[LegalAreaProps] | None = None
    """How the WTI of a BWB regulation files it by legal area (`normalize bwb`)."""
    policy_domains: list[PolicyDomainProps] | None = None
    """How the WTI of a BWB regulation files it by government theme (`normalize bwb`)."""
    bwb_id: str | None = None
    """The BWB id: `BWBR0001854`, a treaty `BWBV...`."""
    celex: str | None = None
    """The CELEX number of an EU act: `32016L0680`."""
    title: str | None = None
    """A BWB regulation its citeertitel, else its intitule; an EU act its printed title;
    a Verdragenbank treaty its Dutch title, else its English one."""
    official_title: str | None = None
    """The `intitule` of its toestand."""
    citation_title: str | None = None
    """The title it is cited by: of an EU act the form of its era (`Richtlijn 95/46/EG`),
    of a publication its name (`Stb. 2019, 33`), of a Verdragenbank treaty its whole
    title."""
    citation_titles: list[str] | None = None
    """Of a BWB regulation: every citation title its WTI gives, the earlier ones too (the
    Participatiewet was the Wet werk en bijstand; `normalize bwb`)."""
    short_title: str | None = None
    """The WTI short title of a BWB regulation; of an EU act the name between brackets that
    ends its title (`Datagovernanceverordening`)."""
    official_id: str | None = None
    """Of a publication: its id at officielebekendmakingen.nl (`stb-2019-33`); of a law the
    BWB does not hold (yet), that of the publication that enacted it (`stb-2026-56`)."""
    abbreviation: str | None = None
    """The abbreviation it is cited by (``core.aliases.abbreviation_of``): `EVRM`, `AVG`."""
    aliases: list[str] | None = None
    """Every name it is cited by: the WTI abbreviations and, for a book of a code, the forms
    "Boek 6 BW", "6 BW", "BW 6", "BW6", "BW Boek 6", "BW"."""
    jurisdiction: str | None = None
    """`nl` (BWB), `eu` (EUR-Lex) or `int` (Verdragenbank)."""
    kind: str | None = None
    """BWB `wetgeving@soort` (`wet`, `AMvB`, ...); a Verdragenbank treaty `verdrag`,
    `bilateraalverdrag` or `multilateraalverdrag`; a publication `publicatie`; a law of the
    Staatsblad the BWB does not hold (yet) `wet`; lower-cased by `semantic
    graph-list-stats`."""
    lang: str | None = None
    """Of an EU act: the language its text was read in."""
    meta: dict[str, Any] | None = None
    """Of an EU act: the `meta` of its raw record."""
    external_id: str | None = None
    """Of a Verdragenbank treaty: its id in the register."""
    uri: str | None = None
    """Of a Verdragenbank treaty: its URI in the register."""
    title_nl: str | None = None
    """Of a Verdragenbank treaty: its Dutch title."""
    title_en: str | None = None
    """Of a Verdragenbank treaty: its English title."""
    treaty_number: str | None = None
    """The six-digit Verdragenbank id, which a BWB treaty names in
    `wetgeving@verdragnummer`."""
    treaty_type: str | None = None
    """Of a Verdragenbank treaty: its type as the register gives it."""
    status: str | None = None
    """Of a Verdragenbank treaty: its status as the register gives it; of a law of the
    Staatsblad the BWB does not hold (yet) `vastgesteld`: its text as published, not in
    force."""
    in_force: bool | None = None
    """Of a Verdragenbank treaty: its status is `inwerkinggetreden`; of a law of the
    Staatsblad the BWB does not hold (yet) `false`."""
    date_signed: str | None = None
    """The day the instrument itself was signed (of a BWB regulation: that of the
    publication that enacted it; of an EU act: the day its title names), not that of an
    amendment."""
    date_in_force: str | None = None
    """The day it came into force (of a BWB regulation: `inwerkingtreding.datum` of the
    `<intitule>`)."""
    version_date_in_force: str | None = None
    """BWB: the start of the toestand in force."""
    date_expired: str | None = None
    """BWB: the first day it was no longer in force (repealed or lapsed); null while in
    force."""
    place_signed: str | None = None
    """Of a Verdragenbank treaty: where it was signed."""
    tractatenblad: list[TreatyPublicationProps] | None = None
    """Of a Verdragenbank treaty: its Tractatenbladen."""
    parties: list[TreatyPartyProps] | None = None
    """Of a Verdragenbank treaty: its state parties."""
    kingdom_parts: list[TreatyKingdomPartProps] | None = None
    """Of a Verdragenbank treaty: the parts of the Kingdom it applies to."""
    kamerstukken: list[TreatyDossierProps] | None = None
    """Of a Verdragenbank treaty: the dossiers of its approval, each once."""
    parent_treaties: list[RelatedTreatyProps] | None = None
    """Of a Verdragenbank treaty: its `Moederverdragen`."""
    child_treaties: list[RelatedTreatyProps] | None = None
    """Of a Verdragenbank treaty: its `Kindverdragen`."""
    article_count: int | None = None
    """Its articles in force, without stubs: the `total` of `/articles` (`semantic
    graph-list-stats`)."""
    inbound_citation_count: int | None = None
    """The `REFERS_TO` edges to it and to its articles and annexes (`semantic
    graph-list-stats`)."""
    amending: bool | None = None
    """A BWB regulation that changes other regulations rather than standing on its own:
    its articles are numbered as a wijzigingsregeling (`Artikel I`) and one or more of them
    changed another regulation, or most of them did (the BWB puts "Wijzigt <regulation>."
    in their place); `semantic graph-list-stats`."""
    publication_kind: str | None = None
    """Of a publication: its journal (`Staatsblad`, `Tractatenblad`, ...)."""
    publication_year: int | None = None
    """Of a publication: its year."""
    publication_number: str | None = None
    """Of a publication: its number in that year."""
    date_published: str | None = None
    """The day it was published (of a BWB regulation: that of the publication that enacted
    it)."""
    dossier_numbers: list[str] | None = None
    """The dossiers of the publication (of a BWB regulation: of the one that enacted
    it)."""
    basis: list[dict[str, Any]] | None = None
    """The `Gelet op` references of its toestand: `{bwb_id, article, doc, text}`
    (`BASED_ON`)."""
    celex_refs: list[str] | None = None
    """The EU acts its text names."""
    implements_celex: list[str] | None = None
    """The EU acts its considerans says it implements (`IMPLEMENTS`)."""
    enacted_publication: str | None = None
    """The publication that enacted it: `stb-2018-144`."""
    unlinked_references: int | None = None
    """Of a law of the Staatsblad: the article references in the text of its articles that
    `semantic staatsblad-law-references` read and could not link (0: it linked every one);
    absent until that step read the law."""
    definitions_found: int | None = None
    """Of a law of the Staatsblad: the definitions `semantic bwb-definitions` read from its
    text; absent until that step read the law."""


# ---------------------------------------------------------------------------
# articles
# ---------------------------------------------------------------------------


class ArticleProps(_CommonProps):
    bwb_id: str | None = None
    """The BWB id of its regulation."""
    celex: str | None = None
    """The CELEX number of its EU act."""
    official_id: str | None = None
    """Of an article of a law the BWB does not hold (yet): the id of the Staatsblad
    publication that enacted its law (`stb-2026-56`; `normalize staatsblad-laws`)."""
    unlinked_references: int | None = None
    """Of an article of a law of the Staatsblad: the article references in its text that
    `semantic staatsblad-law-references` read and could not link (0: it linked every one);
    absent until that step read it."""
    article_number: str | None = None
    """As printed (`287`, `bijlage 2 artikel 9`); `enig-artikel` for the one article of a
    regulation of one article; null for an article with only a heading and for a historical
    identity."""
    label: str | None = None
    """`Artikel 287`, or the heading of an article without a number: `Algemene bepaling`."""
    heading: str | None = None
    """The `<titel>` of its `<kop>` (`Definities`), of an EU article the line under
    "Artikel N"; absent when the source prints none."""
    caption: str | None = None
    """What it is about, for its title: the deepest division title only one division of its
    law has ("Onrechtmatige daad" for 6:162 BW; `semantic bwb-captions`)."""
    position: int | None = None
    """Its place in the current toestand (of an EU article: in the act): the order of the
    lists."""
    text: str | None = None
    """Its text: a lid as `1. text`, list items on their own lines, a paragraph beside the
    leden included."""
    instrument_citation_title: str | None = None
    """The citation title of its instrument."""
    instrument_abbreviation: str | None = None
    """The `abbreviation` of its instrument: "art. 8 EVRM" (`normalize bwb`)."""
    stam_id: str | None = None
    """The BWB `stam-id`, the same across versions and renumbering."""
    versie_id: str | None = None
    """The BWB `versie-id` of its current version."""
    path: str | None = None
    """`bwb-ng-variabel-deel` of its current version: `/Hoofdstuk1/Artikel7`; where a
    definition of its law holds (``core.bwb_definitions.applies``)."""
    valid_from: str | None = None
    """`inwerking` of its current version."""
    source_publication: str | None = None
    """`bron` of its current version: "Stb.2019-33"; of an article of a law of the
    Staatsblad the publication its text comes from: "Stb. 2026, 57"."""
    repealed: bool | None = None
    """A historical identity, or a current article whose latest `effect` is `vervallen`."""
    last_article_number: str | None = None
    """Of a historical identity: its last known number."""
    parts: list[dict[str, Any]] | None = None
    """The structure of its text: `{id, kind, number, start, end, term}`, offsets into
    `text`."""
    tables: list[dict[str, Any]] | None = None
    """The tables in its text: `{start, end, head_rows, columns, spans}`, offsets into
    `text`, a row a line and its cells separated by a tab; absent without tables."""
    headings: list[dict[str, Any]] | None = None
    """The headings in its text, each on a line of its own (a `<tussenkop>`, the title of a
    table): `{start, end}`, offsets into `text`; absent without headings."""
    footnote_marks: list[dict[str, Any]] | None = None
    """Where the marker of a footnote (`<sup>1</sup>`, a `<noot>`) stood in its text, which
    leaves it out: `{at, number}`, `text[:at]` the words before it; the footnote itself is a
    paragraph of `text` that opens with its number, or, with `footnote`, the one of
    `footnotes` at that place. Absent without footnotes."""
    footnotes: list[dict[str, Any]] | None = None
    """The footnotes its source writes where their marker stands (`<noot>`), not in `text`:
    `{number, text}`, in text order, those of its heading (without a marker) first; their
    links are `references` with `footnote`. Absent without one."""
    references: list[dict[str, Any]] | None = None
    """Every `extref`/`intref` of its text that names a regulation, an annex or an EU act:
    `{kind, bwb_id, article, doc, text, start, end, leden, onderdelen, aanhef}`, `celex` of
    an EU act, `annex` the key of the annex linked to; one of a footnote with `footnote`,
    its place in `footnotes`, `start` and `end` offsets into that footnote's text."""
    breadcrumb: list[dict[str, Any]] | None = None
    """The divisions that hold it, outermost first: `{type, label, title}`; absent outside
    every division."""
    inbound_citation_count: int | None = None
    """The `REFERS_TO` and `EXPLAINS` edges to it (`semantic graph-list-stats`)."""


# ---------------------------------------------------------------------------
# instrument_versions
# ---------------------------------------------------------------------------


class InstrumentVersionProps(_CommonProps):
    bwb_id: str | None = None
    """The BWB id of its regulation."""
    valid_from: str | None = None
    """The start of the toestand."""
    valid_until: str | None = None
    """The day after its last day (exclusive); null when open."""
    current: bool | None = None
    """It is the toestand in force."""
    state_url: str | None = None
    """`locatie_toestand` of its SRU record: where its XML is."""


# ---------------------------------------------------------------------------
# article_versions
# ---------------------------------------------------------------------------


class ArticleVersionProps(_CommonProps):
    bwb_id: str | None = None
    """The BWB id of its regulation."""
    last_seen: str | None = None
    """The start of the latest toestand that holds this version (`normalize
    bwb-history`)."""
    article_number: str | None = None
    """As printed."""
    label: str | None = None
    """As on Article."""
    heading: str | None = None
    """As on Article."""
    position: int | None = None
    """Its place in one order of all versions of the law, in which the versions of every
    toestand keep theirs."""
    valid_from: str | None = None
    """The article's own `inwerking`."""
    valid_until: str | None = None
    """`valid_from` of the next version of the same article (the first day it no longer
    holds); its own `valid_from` for a version that says the article lapsed; the start of
    the first toestand without it for an article that left the law; null when current."""
    current: bool | None = None
    """It is the version in force."""
    text: str | None = None
    """As on Article."""
    instrument_citation_title: str | None = None
    """The citation title of its instrument."""
    stam_id: str | None = None
    """The BWB `stam-id` of its article."""
    versie_id: str | None = None
    """The BWB `versie-id`."""
    path: str | None = None
    """`bwb-ng-variabel-deel`: `/Hoofdstuk1/Artikel7`."""
    parts: list[dict[str, Any]] | None = None
    """As on Article: offsets into `text`."""
    tables: list[dict[str, Any]] | None = None
    """As on Article: offsets into `text`."""
    headings: list[dict[str, Any]] | None = None
    """As on Article: offsets into `text`."""
    footnote_marks: list[dict[str, Any]] | None = None
    """As on Article: offsets into `text`."""
    footnotes: list[dict[str, Any]] | None = None
    """As on Article."""
    effect: str | None = None
    """BWB effect: `nieuw`, `wijziging`, `vervallen`, ..."""
    source_publication: str | None = None
    """`bron`: "Stb.2019-33"."""
    origin_publication: dict[str, Any] | None = None
    """The publication it came from: id, kind, year, number, effect, signed, published,
    dossiers."""
    commencement_publication: dict[str, Any] | None = None
    """The publication that brought it into force, likewise."""
    content_digest: str | None = None
    """Of label, heading, place and text: equal for a version that only repeats the one
    before."""
    breadcrumb: list[dict[str, Any]] | None = None
    """The divisions that held it in the first toestand that holds it, outermost first:
    `{type, label, title}` (`normalize bwb-history`)."""
    breadcrumb_changes: list[dict[str, Any]] | None = None
    """The days from which it stood under other divisions, oldest first: `{from,
    breadcrumb}`, `from` the start of the first toestand with them; absent when it never
    moved."""


# ---------------------------------------------------------------------------
# judgments
# ---------------------------------------------------------------------------


class JudgmentParagraphProps(_StrictBase):
    """One paragraph of a judgment (``core.judgment_paragraphs.judgment_text``)."""

    id: str
    """`rov-5.3`, `kop-5`, `p-3f2a9c1e`, `par-12`: unique in the judgment, for deep links."""
    number: str | None = None
    """As printed, without its closing dot: "5.3"; null when it has none."""
    kind: Literal["heading", "subheading", "body", "signature", "toc"]
    """What the paragraph is."""
    text: str
    """Its text, without its number."""
    continues: str | None = None
    """Of a `body` paragraph without a number: the `id` of the numbered consideration it
    goes on with."""
    tables: list[dict[str, Any]] | None = None
    """The tables in its text: `{start, end, head_rows, columns, spans}` (as on Article),
    offsets into `text`; absent without tables."""


# Who acts for a party, by the word the judgment gives (``raadsman``: criminal cases only),
# and the side of the case a party is on.
CounselRole = Literal["advocaat", "gemachtigde", "raadsman"]
PartySide = Literal["first", "second", "other"]


class JudgmentRepresentativeProps(_StrictBase):
    """Who acts for a party of a judgment, as its kop or its account of the procedure
    names them (``core.judgment_counsel``)."""

    name: str
    """As written, titles and all: "mr. drs. R. van Gelder"."""
    role: CounselRole
    """The word the text gives; else `gemachtigde` for who represents a party and
    `raadsman` for who assists a suspect (`raadsman` in a criminal case only)."""
    place: str | None = None
    """Where they practise: "Voorschoten"."""
    capacity: str | None = None
    """What else the text calls them: "ambtenaar in dienst van de provincie"."""


class JudgmentPartyProps(_StrictBase):
    """One party of a judgment (``core.judgment_parties.read_parties``)."""

    name: str
    """As the judgment writes it, anonymised where the source is (`[eiser]`), without its
    legal form, place or role."""
    role: str
    """`Verdachte`, `Eiser`, `Verweerder`, `Appellant`, `Belanghebbende`, ...; `Partij`
    when none applies."""
    roles: list[str] = []
    """Every role the judgment names for the party, in its order; `[role]` when it names
    none."""
    role_stated: bool
    """The judgment names the role; false when it is derived from the area of law and the
    side."""
    side: PartySide
    """`first` before "tegen" or "en", `second` after it, `other` for a belanghebbende that
    is not the first party."""
    alias: str | None = None
    """What the judgment calls it: `EBN` for "hierna: EBN"."""
    representatives: list[JudgmentRepresentativeProps] = []
    """Who acts for the party, each person once. An expert, interpreter or witness is no
    representative."""


class JudgmentAppealTargetProps(_StrictBase):
    """A decision an appeal says it appeals that is not loaded (``core.appeals``)."""

    court: str
    """As the text writes it: "rechtbank Gelderland"."""
    date: str
    """ISO."""
    case_number: str | None = None
    """As the text writes it: "24/6811"; null when it gives none."""


class JudgmentUnresolvedCitationProps(_StrictBase):
    """A citation of a law that is not in the graph (``semantic rechtspraak``,
    ``core.mentions.ArticleMentions.unresolved``)."""

    law: str
    """As the text writes it ("Rv", "Vw 2000"), or the law a short name the judgment
    defines stands for."""
    article_number: str
    """As written."""
    raw_match: str
    """The first citation: "art. 392 Rv"."""
    qualifier: str | None = None
    """Of the first citation: "derde lid"."""
    leden: list[str] = []
    """The leden it names, as in the part ids of an article."""
    onderdelen: list[str] = []
    """The onderdelen it names, likewise."""
    aanhef: bool = False
    """It names the aanhef."""
    paragraph_ids: list[str] = []
    """The paragraphs that cite it."""
    mention_count: int = 1
    """How often the judgment cites it."""


class JudgmentProps(_CommonProps):
    ecli: str | None = None
    """Its ECLI."""
    source_kind: str | None = None
    """The kind of the raw record it was read from (`rs-content`)."""
    meta: dict[str, Any] | None = None
    """The `meta` of its raw record."""
    summary: str | None = None
    """The inhoudsindicatie, in Dutch; null for a placeholder ("kopje volgt", "-")."""
    summary_en: str | None = None
    """An English inhoudsindicatie: of a translation, and of the judgment it translates."""
    translation_of: str | None = None
    """Of an English translation: the ECLI of the judgment it translates."""
    names: list[str] | None = None
    """What lawyers call it (`Haviltex`; ``core.judgment_names``)."""
    decision_kind: str | None = None
    """`arrest`, `vonnis`, `beschikking`, `uitspraak`, `beslissing`, `conclusie` or
    `prejudiciële beslissing` (``core.judgment_kinds.judgment_kind``)."""
    text: str | None = None
    """Every paragraph as printed, a blank line between."""
    judgment_metadata: dict[str, Any] | None = None
    """Its RDF header: `type`, the procedure, `document_type` (`Uitspraak` or
    `Conclusie`), `court`, `date`, `case_number`, the related ECLIs, ..."""
    subjects: list[str] | None = None
    """Its areas of law as the metadata gives them ("Civiel recht; Verbintenissenrecht")."""
    paragraphs: list[JudgmentParagraphProps] | None = None
    """The `<uitspraak>` (of a conclusion: the `<conclusie>`) in reading order; the first is
    the kop."""
    footnotes: list[dict[str, Any]] | None = None
    """Its footnotes, which are no paragraph: `{label, paragraph_id, text, at}`;
    `paragraph_id` the paragraph that refers to it (null when none does), `at` where that
    marker stands in its text (``core.judgment_paragraphs.judgment_text``)."""
    parties: list[JudgmentPartyProps] | None = None
    """What the kop names, in its order, then a party the account of the procedure hears
    "als partij"; `[]` when neither names one, absent when not read yet."""
    advocate_general: str | None = None
    """Of a conclusion: who wrote it, as its kop names them
    (``core.judgment_advocate_general.advocate_general``)."""
    advocate_general_role: str | None = None
    """The role they sign in: `advocaat-generaal`, `waarnemend advocaat-generaal`,
    `plaatsvervangend procureur-generaal` or `plaatsvervangend advocaat-generaal`
    (``core.judgment_advocate_general.advocate_general_role``)."""
    court: str | None = None
    """The court as the metadata names it."""
    case_number: str | None = None
    """As the metadata gives it."""
    case_number_keys: list[str] | None = None
    """`case_number` split and written as compared (``core.case_numbers.case_number_keys``)."""
    related_eclis: list[str] | None = None
    """The earlier instances the metadata names (`dcterms:relation`)."""
    later_eclis: list[str] | None = None
    """The later instances it names (`psi:aanleg` latereAanleg): the courts that ruled on
    appeal of it, in cassation or after it."""
    conclusion_eclis: list[str] | None = None
    """The conclusion of a judgment, or the judgment of a conclusion (`psi:type`
    conclusie)."""
    unresolved_appeal_targets: list[JudgmentAppealTargetProps] | None = None
    """The decisions an appeal names in its text that are not loaded (`semantic
    rechtspraak-appeal`); null when there are none."""
    unresolved_citations: list[JudgmentUnresolvedCitationProps] | None = None
    """The articles it cites of laws that are not in the graph, the first 100, in reading
    order (`semantic rechtspraak`); null when there are none."""
    court_code: str | None = None
    """The court of its ECLI (`HR`, `GHAMS`)."""
    tier: str | None = None
    """The `Type` of its court in the Instanties list."""
    court_kind: str | None = None
    """The kind of court within that tier."""
    date_eff: str | None = None
    """Its date: of the metadata, else of the raw record."""
    published_on: str | None = None
    """"Datum publicatie": the `dcterms:issued` of the published document
    (``core.judgment_metadata.published_on``); null without the document."""
    inbound_citation_count: int | None = None
    """The judgments that cite it or a publication `SAME_AS` it, each once (`semantic
    graph-list-stats`)."""
    outbound_citation_count: int | None = None
    """The judgments it cites (`semantic graph-list-stats`)."""
    replaced_by: str | None = None
    """`dcterms:isReplacedBy`: the ECLI of the publication of the same decision that
    replaces this one."""
    withdrawn: str | None = None
    """How the Rechtspraak withdrew it (`deleted` of its index entry): `doc` (the document
    is no longer published) or `ecli` (the ECLI was given in error; `replaced_by` the one
    the source names instead, if it names one). The judgment is then a stub with the facts
    of the decision that name no one: `ecli`, `court` and its codes, `date`, `date_eff`,
    `case_number(_keys)`, `decision_kind`, `subjects`. Null while it is published."""
    withdrawn_on: str | None = None
    """The day it was withdrawn (Dutch time, of the `updated` of its index entry)."""
    same_as: str | None = None
    """That publication, when it is loaded (`semantic rechtspraak-duplicates`): this one is
    `SAME_AS` it and left out of the lists. Of an ECHR language version without an ECLI:
    the item id of the one kept (`semantic echr-versions`)."""
    series_id: str | None = None
    """Of parallel cases of one court and day (`semantic rechtspraak-series`): the lowest
    ECLI of the series; null outside a series."""
    series_size: int | None = None
    """How many judgments the series has."""
    external_id: str | None = None
    """ECHR: the HUDOC item id; CJEU: the CELEX number."""
    celex: str | None = None
    """CJEU: the CELEX number (sector 6: ``62018CJ0311``)."""
    appno: str | None = None
    """ECHR: the application number."""
    language: str | None = None
    """ECHR: the language of the HUDOC record (`ENG`, `FRE`)."""
    title: str | None = None
    """ECHR: the name of the case; CJEU: its parties as CELLAR names them."""
    date: str | None = None
    """The day of the decision."""
    respondent: str | None = None
    """ECHR: the respondent state."""
    originating_body: str | None = None
    """ECHR: the formation that decided."""
    articles: list[str] | None = None
    """ECHR: the articles of the Convention the record names."""
    conclusion: str | None = None
    """ECHR: the conclusion of the record ("Violation of Article 8 - ...")."""
    importance: int | None = None
    """ECHR: the importance level of the record."""
    outcome: str | None = None
    """How it ended, as the first clause of its decision says it (`verworpen`,
    `vernietigd`, ...; ``core/judgment_outcome.py``); of an ECHR judgment `schending` or
    `geen schending` (``core/echr_findings.py``); null when the text does not say it."""
    outcome_text: str | None = None
    """The clause (at most 300 characters), or the ECHR finding."""
    outcome_paragraph_id: str | None = None
    """The paragraph of that clause."""
    conclusion_outcome: str | None = None
    """Of a conclusion: what it proposes (`verwerping`, `vernietiging`, ...)."""
    conclusion_outcome_text: str | None = None
    """The sentence that says it."""
    conclusion_outcome_paragraph_id: str | None = None
    """The paragraph of that sentence."""
    echr_findings: list[dict[str, Any]] | None = None
    """ECHR: what it found per article, read from `conclusion`: `{article, protocol,
    combined_with, finding, aspect, text}` (``core/echr_findings.py``)."""


# ---------------------------------------------------------------------------
# documents  (TK, TK-dossier docs, Staatsblad, Staatscourant, Eerste Kamer)
# ---------------------------------------------------------------------------


class DocumentActorProps(_StrictBase):
    """One who signed a document (``tk_records.actors.document_actors``; of a motion of the
    Eerste Kamer, ``normalize eerstekamer-motions``)."""

    name: str
    """As the source writes it."""
    person_id: str | None = None
    """The member who signed."""
    faction_id: str | None = None
    """The faction signed for."""
    faction: str | None = None
    """That faction as the source writes it."""
    role: str | None = None
    """`DocumentActor.Relatie`; of a motion of the Eerste Kamer `Eerste ondertekenaar` or
    `Mede ondertekenaar`."""
    function: str | None = None
    """The function they signed in (`DocumentActor.Functie`) as the source writes it:
    `Tweede Kamerlid`, `minister-president`."""
    capacity: str | None = None
    """What that makes the signature (`tk_records.actors.signing_capacity`):
    `bewindspersoon`, `kamerlid` or `overig`."""


class DocumentProps(_CommonProps):
    external_id: str | None = None
    """The id of its record (TK `Document.Id`)."""
    raw: dict[str, Any] | None = None
    """The record of the Tweede Kamer as it came."""
    dictum: str | None = None
    """Of a motion, what it asks or says as it writes it: the lines from the first that
    begins with `verzoekt`, `roept`, `spreekt`, `draagt` or `vraagt` to `en gaat over tot
    de orde van de dag`, joined (``core/motion_dictum.py``); absent for any other paper
    and for a text without that closing formula. Also kept by `semantic tk-dictum` for
    the motions whose text was read before."""
    explanation: str | None = None
    """Of an amendment, what it is for: the first paragraph of its "Toelichting", whole
    sentences up to 400 characters, else cut at a word with "…"
    (``core/amendment_explanation.py``); absent for any other paper and for one without a
    Toelichting."""
    outcome: str | None = None
    """Of a motion or an amendment, how it ended (`semantic tk-paper-outcomes`,
    ``core/votes.py``): `aangenomen`, `verworpen`, `ingetrokken`, `aangehouden`,
    `vervallen` or `vervangen`."""
    decided_on: str | None = None
    """The day of the decision that gave the outcome; null without one."""
    tally: dict[str, int] | None = None
    """The seats per choice of that decision."""
    decision: str | None = None
    """The key of that decision."""
    motion_kind: str | None = None
    """Of a motion of censure `censure` (motie van afkeuring), of no confidence
    `no_confidence` (motie van wantrouwen), from the fixed wording of its subject
    (`semantic tk-motion-kinds`, ``core/motion_kinds.py``); absent for any other paper."""
    summary: str | None = None
    """Of a motion of the Eerste Kamer (`normalize eerstekamer-motions`): what it asks as
    its page opens."""
    submitted_on: str | None = None
    """Of such a motion: the day it was submitted."""
    debate: str | None = None
    """Of such a motion: the debate it was submitted at."""
    status: str | None = None
    """Of such a motion: its `behandelstatus` as the Kamer writes it."""
    motion_url: str | None = None
    """Of such a motion: its page."""
    pdf_url: str | None = None
    """Of such a motion: its PDF."""
    title: str | None = None
    """`Titel`; of a motie, amendement, letter or report its own `Onderwerp`, else that of
    its zaak."""
    dossier_title: str | None = None
    """Of a document named by its own subject: its `Titel`, the title of its dossier."""
    subject: str | None = None
    """Its `Onderwerp`."""
    kind: str | None = None
    """`Document.Soort`; one that contains `toelichting` makes it explanatory."""
    date: str | None = None
    """Its date."""
    number: str | None = None
    """Its own number: a Kamerstuk number, or that of a Staatsblad or Staatscourant."""
    text: str | None = None
    """Its text (`normalize tk-content`): one line per heading, paragraph, list item or
    table row (cells tab-separated), whitespace collapsed; footnotes, header and signature
    are not in it. Cut at a whole line at 2,000,000 characters (`MAX_TEXT_CHARS`)."""
    text_source: str | None = None
    """`kst-xml`."""
    text_truncated: bool | None = None
    """`true` when the text was cut."""
    xml_dialect: str | None = None
    """`kamerwrk` (1995-2009) or `officiele-publicatie` (2010 on)."""
    structure_quality: str | None = None
    """`explicit` (an artikelsgewijs opener and article headings after it), `implicit`
    (article headings, no opener) or `none`."""
    budget: bool | None = None
    """A budget or annual report (a dossier chapter such as `XV`, or a title that says
    so): its numbered articles are policy articles, not law articles, so a consumer that
    links articles skips it."""
    sections: list[dict[str, Any]] | None = None
    """The headings of the paper in document order, each spanning its body and what is
    nested under it: `{id, heading, level, parent, kind, number, number_scheme,
    article_refs, law, char_start, char_end}`."""
    footnotes: list[dict[str, Any]] | None = None
    """`{number, text, at}` in document order; `at` is where its marker stood in `text`
    (`text[:at]` the words before it), absent for a footnote without a marker in the text
    kept (one of the header, a legacy `voetnoot` no `voetref` names)."""
    paragraphs: list[dict[str, Any]] | None = None
    """Each line of `text` in order (``core/document_paragraphs.py``): `{id, number, kind,
    char_start, char_end}`. `kind` is `head` (title and date of the stuk), `heading`,
    `formula` (of a motion: `De Kamer, gehoord de beraadslaging,` and from `en gaat over tot
    de orde van de dag` on), `table` (its title and rows) or `body`; `number` the alinea, from
    1, of a `body` line and of a table (all its lines one number), null for the others; `id`
    `p-` and 8 hex of its text, `_<n>` for its n-th repeat."""
    tables: list[dict[str, Any]] | None = None
    """The tables in its text: `{start, end, head_rows, columns, spans}` (as on Article),
    offsets into `text`; null without tables."""
    dossier_number: str | None = None
    """`Document.Kamerstukdossier`: the one dossier it is a Kamerstuk of; null for a paper
    that is none."""
    dossier_suffix: str | None = None
    """The addition to the dossier number: the chapter `VII` of `35925 VII`."""
    dossier_numbers: list[str] | None = None
    """The dossiers of its cases and its own, as labels."""
    case_ids: list[str] | None = None
    """Its cases."""
    case_kinds: list[str] | None = None
    """The `Zaak.Soort` of those cases (`Wetgeving`, `Motie`, `Brief regering`, ...)."""
    sequence: int | None = None
    """Its number within `dossier_number`."""
    session_year: str | None = None
    """Its vergaderjaar."""
    document_number: str | None = None
    """`DocumentNummer` (`2026D44984`), by which tweedekamer.nl finds it."""
    actors: list[DocumentActorProps] | None = None
    """Every signature."""
    activity_ids: list[str] | None = None
    """`Document.Activiteit`: the activities it is the record of (a stenogram: its debate;
    `MADE_IN`)."""
    attachment_ids: list[str] | None = None
    """`BijlageDocument`: its attachments (`ACCOMPANIES`)."""
    attached_to_ids: list[str] | None = None
    """`BronDocument`: the letters it is an attachment of."""
    url: str | None = None
    """Of a document of the Eerste Kamer: its page on officielebekendmakingen.nl, as the
    source gives it."""
    identifier: str | None = None
    """Of a Staatsblad or Staatscourant publication: its identifier."""
    year: str | None = None
    """Of such a publication: its year."""
    bwb_id: str | None = None
    """Of such a publication: the regulation it is about."""


# ---------------------------------------------------------------------------
# dossiers
# ---------------------------------------------------------------------------


class DossierPhaseProps(_StrictBase):
    """A phase of a bill (``core.dossier_stages.dossier_phases``)."""

    name: str
    """The phase, as the curated list names it."""
    done: bool
    """A record of the dossier marks it."""
    date: str | None = None
    """The first date of the records that mark it."""


class TkDecisionProps(_StrictBase):
    """The last decision of the Tweede Kamer on a bill (``dossier_stages.last_decision``)."""

    kind: str
    """Its `BesluitSoort`."""
    text: str | None = None
    """Its text."""
    date: str | None = None
    """Its day."""


class EkRejectedProps(_StrictBase):
    """The day the Eerste Kamer rejected a bill, from its list of rejected bills."""

    date: str
    """The day."""
    source_url: str | None = None
    """The list."""
    retrieved_on: str | None = None
    """The day it was read."""


class EkOutcomeProps(_StrictBase):
    """The outcome of a bill in the Eerste Kamer (``dossier_stages.ek_outcome``)."""

    outcome: str
    """`Aangenomen` or `Verworpen`."""
    date: str | None = None
    """The day."""
    method: str | None = None
    """How it was decided, as eerstekamer.nl writes it."""
    source_url: str | None = None
    """The page it was read from."""
    retrieved_on: str | None = None
    """The day it was read."""


class EkBillDocumentProps(_StrictBase):
    """A document of a step of a bill page (``core.ek_bills.Document``)."""

    kind: str
    """As the page names it."""
    date: str | None = None
    """Its date."""
    number: str | None = None
    """Its number."""
    url: str | None = None
    """Its link."""


class EkBillStepProps(_StrictBase):
    """A step of the progress block of a bill page (``core.ek_bills.Step``)."""

    phase: str | None = None
    """The phase, as the page names it."""
    house: str | None = None
    """The chamber of the step."""
    state: str | None = None
    """As the page marks it: `vol`, `geblokt`, `leeg`."""
    papers: list[EkBillDocumentProps] = []
    """Its papers."""


class EkBillProps(_StrictBase):
    """The page of a bill on eerstekamer.nl (``normalize eerstekamer-bills``)."""

    url: str | None = None
    """The page."""
    read_on: str | None = None
    """The day it was read."""
    status: str | None = None
    """The status the page gives."""
    submitted_on: str | None = None
    """The day it was submitted, as the page gives it."""
    progress: list[EkBillStepProps] = []
    """The steps of its progress block."""


class DossierProps(_CommonProps):
    external_id: str | None = None
    """The id of its `Kamerstukdossier` record."""
    number: str | None = None
    """`37020`."""
    suffix: str | None = None
    """`XV`."""
    label: str | None = None
    """`37020-XV`; the key is made from it."""
    order: str | None = None
    """A text that sorts dossiers as the Kamer does: by number, then no suffix, numeric
    suffixes, budget chapters, the rest (``core/dossier_numbers.dossier_order``)."""
    title: str | None = None
    """Its title."""
    title_source: str | None = None
    """Where the title comes from."""
    closed: bool | None = None
    """It has an outcome (`semantic tk-dossier-outcomes`); `false` for an open dossier."""
    opened_on: str | None = None
    """The date of nr. 1 of its own numbering, else of its Koninklijke boodschap, else of
    its first document or activity."""
    opened_on_basis: str | None = None
    """Where `opened_on` comes from: `first_paper`, `royal_message` or
    `earliest_record`."""
    last_activity: str | None = None
    """The day of its newest document, activity that took place or decision; refreshed by
    every `normalize tk-dossiers` that touches it."""
    submitted_on_tk: str | None = None
    """The `Zaak.GestartOp` of its own zaak of a bill (`Wetgeving`,
    `Initiatiefwetgeving`, `Begroting`): the day the Kamer dates its submission."""
    closed_on: str | None = None
    """The day of its outcome."""
    case_kinds: list[str] | None = None
    """The `Zaak.Soort` of its own cases."""
    kind: str | None = None
    """What the dossier is: the `Zaak.Soort` of its own zaak (`Wetgeving`, `Begroting`,
    `Verdrag`, ...; ``core/dossier_stages.CARRYING_KINDS``); null without such a zaak.
    Never read from its papers."""
    kind_basis: str | None = None
    """`case` when its zaak gives the kind, else null."""
    phases: list[DossierPhaseProps] | None = None
    """Of a `Wetgeving`, `Initiatiefwetgeving` or `Begroting`: every phase of the curated
    list `phases` in its order. A phase is done when a paper, an activity that took place
    or a decision on the dossier's own zaak has a value the list names for it."""
    current_phase: str | None = None
    """The furthest done phase."""
    outcome: str | None = None
    """`aangenomen` when its law was published or the Eerste Kamer adopted it, `verworpen`
    when a chamber voted the bill down, `ingetrokken` when the government withdrew it by
    letter (`semantic tk-dossier-outcomes`)."""
    withdrawal_letter: str | None = None
    """Of a withdrawn bill, the id of the letter that withdrew it: a `Brief regering` whose
    `Onderwerp` is the fixed title `Brief houdende intrekking van het wetsvoorstel`
    (``core/dossier_stages.WITHDRAWAL_LETTER_SUBJECT``)."""
    tk_decision: TkDecisionProps | None = None
    """The last decision of the Tweede Kamer on its bill."""
    ek_rejected: EkRejectedProps | None = None
    """The Eerste Kamer's list of rejected bills names it (`normalize
    eerstekamer-votes`)."""
    ek_outcome: EkOutcomeProps | None = None
    """Its outcome in the Eerste Kamer."""
    ek_bill: EkBillProps | None = None
    """The page of its bill on eerstekamer.nl (`normalize eerstekamer-bills`)."""
    ministry: str | None = None
    """Who brought it in (`semantic tk-government`): the ministry of the bewindspersoon who
    first signed its earliest signed document."""
    initiative: bool | None = None
    """`true` when a Kamerlid signed first."""
    cabinet: str | None = None
    """The cabinet in office that day."""
    first_signed: dict[str, Any] | None = None
    """The signature `ministry`, `initiative` and `cabinet` are read from (`semantic
    tk-government`): the first of the earliest document of the dossier signed first by a
    Kamerlid or a bewindspersoon, `{date, member, capacity, function, paper}` (`member` its
    key, `capacity` `kamerlid` or `bewindspersoon`, `paper` the id of the document)."""
    same_number_count: int | None = None
    """The other dossiers with the same number (`normalize tk-dossiers`)."""


# ---------------------------------------------------------------------------
# activities
# ---------------------------------------------------------------------------


class DecisionPointProps(_StrictBase):
    """A decision point of a committee meeting of the Eerste Kamer
    (``core.ek_agenda.DecisionPoint``)."""

    id: str
    """Its id on the agenda."""
    number: str
    """Its number on the agenda."""
    reference: str
    """The reference the agenda gives it."""
    dossiers: list[str] = []
    """The dossiers it is about."""
    subject: str | None = None
    """What it is about."""
    decision: str | None = None
    """The decision, as the committee words it."""


class ActivityProps(_CommonProps):
    external_id: str | None = None
    """The id of its `Activiteit` record."""
    date: str | None = None
    """Its date."""
    precision: str | None = None
    """`Activiteit.DatumSoort`, how precise `date` is: `Dag`, `Weeknummer` (planned for the
    week of that Monday), `Meerdaags` (its first day); none of the Eerste Kamer."""
    agenda_title: str | None = None
    """Its `Onderwerp`; of the Eerste Kamer the block's title, or the committees."""
    kind: str | None = None
    """Its kind (a debate, a hearing); of the Eerste Kamer `plenaire vergadering` or the
    kind of a meeting as its agenda gives it."""
    status: str | None = None
    """`Activiteit.Status` as the Kamer writes it: `Gepland`, `Uitgevoerd`, `Geannuleerd`,
    `Verplaatst`, `Vervallen`; none of the Eerste Kamer."""
    committee_id: str | None = None
    """Its committee; null for a plenary activity."""
    case_ids: list[str] | None = None
    """The cases it is about."""
    dossier_numbers: list[str] | None = None
    """The dossiers it is about."""
    case_kinds_by_dossier: dict[str, list[str]] | None = None
    """The `Zaak.Soort` of its cases per dossier."""
    number: str | None = None
    """`Activiteit.Nummer`, by which tweedekamer.nl finds it."""
    replaced_by: list[str] | None = None
    """`Activiteit.VervangenDoor`: the numbers of the activities that replace it."""
    chamber: str | None = None
    """`EK` for the Eerste Kamer (`normalize eerstekamer-agenda`)."""
    time: str | None = None
    """Of the Eerste Kamer: the time as its agenda gives it."""
    decision_points: list[DecisionPointProps] | None = None
    """Of a committee meeting of the Eerste Kamer: its decision points."""
    source_url: str | None = None
    """Of the Eerste Kamer: the page it was read from."""
    retrieved_on: str | None = None
    """Of the Eerste Kamer: the day it was read."""


# ---------------------------------------------------------------------------
# decisions
# ---------------------------------------------------------------------------


class DecisionProps(_CommonProps):
    decision_id: str | None = None
    """The `Besluit`."""
    agenda_item_id: str | None = None
    """Its agendapunt."""
    activity_id: str | None = None
    """The activity of its agendapunt, the meeting it was taken in (`MADE_IN`)."""
    date: str | None = None
    """The day."""
    subject: str | None = None
    """What the decision is about."""
    agenda_item_subject: str | None = None
    """What its agendapunt is about."""
    decision_text: str | None = None
    """Its text."""
    decision_kind: str | None = None
    """`BesluitSoort` as the Kamer writes it: `Stemmen - aangenomen`, `Stemmen - zonder
    stemming aannemen`, `Stemmen - uitstellen`, ..."""
    decision_order: int | None = None
    """Its order on the agendapunt (`AgendapuntZaakBesluitVolgorde`)."""
    meeting_kind: str | None = None
    """The kind of meeting (`Vergadering_Soort`)."""
    case_ids: list[str] | None = None
    """The cases it is about."""
    primary_case_id: str | None = None
    """The zaak it decided."""
    primary_case_kind: str | None = None
    """The `Zaak.Soort` of that zaak: `Wetgeving` on the vote on a bill itself."""
    dossier_numbers: list[str] | None = None
    """The dossiers it is about."""
    vote_kind: str | None = None
    """`member` on a roll call (every row a member), `faction` otherwise; null for a
    decision on a bill without votes (a hamerstuk, from a `tk-besluit` record, which has no
    `tally` either)."""
    tally: dict[str, int] | None = None
    """Seats per choice: a member one, a faction its seats without its members who voted
    apart. Who voted how is on the `VOTED` edges."""
    voters: dict[str, int] | None = None
    """How many rows cast each choice."""
    passed: bool | None = None
    """From the `BesluitSoort`, else the tally; null for a decision that is no vote."""
    external_id: str | None = None
    """The id of its `Besluit` record."""
    kind: str | None = None
    """What was decided on: the `Zaak.Soort` of the primary case, else the one Soort of the
    cases on its agendapunt (``tk_records.decisions.decided_case_kind``); of the Eerste Kamer
    the kind of the bill's dossier, or `Motie`. Never read from the subject."""
    chamber: str | None = None
    """`TK`, or `EK` for a vote of the Eerste Kamer (`normalize eerstekamer-votes`)."""
    motion_kind: str | None = None
    """Of a vote on a motion of censure `censure`, of no confidence `no_confidence`, from
    the fixed wording of its subject (`semantic tk-motion-kinds`, ``core/motion_kinds.py``);
    absent for any other decision."""
    result: str | None = None
    """Of a vote of the Eerste Kamer: the outcome eerstekamer.nl shows (`Aangenomen`,
    `Verworpen`)."""
    method: str | None = None
    """How it was decided (`Hamerstuk`, `Stemming bij zitten en opstaan, aangenomen`)."""
    factions_for: list[str] | None = None
    """The factions for."""
    factions_against: list[str] | None = None
    """The factions against."""
    factions_noted: list[str] | None = None
    """The factions that asked to have their vote recorded."""
    bill_url: str | None = None
    """The page of the bill."""
    source_url: str | None = None
    """The page of the report it was read from."""
    retrieved_on: str | None = None
    """The day it was read."""
    bill_decision: bool | None = None
    """It is the vote that decided the bill (`semantic tk-dossier-outcomes`)."""
    letter: str | None = None
    """Of a vote on a motion: the motion's letter in its dossier."""
    motion_url: str | None = None
    """Of a vote on a motion: its page (`/motiedossier/...`)."""


# ---------------------------------------------------------------------------
# commitments
# ---------------------------------------------------------------------------


class CommitmentProps(_CommonProps):
    external_id: str | None = None
    """The id of its `Toezegging` record."""
    text: str | None = None
    """The commitment."""
    minister_name: str | None = None
    """Who made it, as the Kamer writes it."""
    minister_role: str | None = None
    """Their role, as the Kamer writes it."""
    ministry_name: str | None = None
    """The ministry the Kamer gives it (`Toezegging.Ministerie`)."""
    made_on: str | None = None
    """The day the Kamer registered it (`Aanmaakdatum`, often weeks after the debate: the
    day it was made is that of its activity)."""
    expected_resolution: str | None = None
    """The day it is due; `0001-01-01` when the Kamer names none."""
    status: str | None = None
    """`Toezegging.Status` as the Kamer gives it: `Openstaand`, `Afgedaan`, `Deels
    Afgedaan`, `Nagekomen`, `Niet nagekomen`, `Vervallen`."""
    activity_number: str | None = None
    """The number of its activity."""
    number: str | None = None
    """`TZ202603-130`, how the Kamer cites it."""
    letter_ids: list[str] | None = None
    """`Toezegging.KamerbriefNakoming`: the letters that fulfil it (TK ids); each stored one
    `ANSWERS` it."""
    letter_dossiers: list[str] | None = None
    """The dossiers those letters are numbered in (`37020`, `36600-VII`): it is `ABOUT` the
    stored ones, before the agenda of its debate."""
    member_key: str | None = None
    """Who made it (`semantic tk-government`; also an `AUTHORED` edge, `role`
    `toezegger`)."""
    post: str | None = None
    """The post they made it in."""
    ministry: str | None = None
    """The ministry of that post."""
    cabinet: str | None = None
    """The cabinet in office that day."""


# ---------------------------------------------------------------------------
# committees
# ---------------------------------------------------------------------------


class CommitteeProps(_CommonProps):
    external_id: str | None = None
    """The id of its `Commissie` record."""
    name: str | None = None
    """Its name."""
    abbreviation: str | None = None
    """Its abbreviation."""
    slug: str | None = None
    """Unique (`GET /api/committees`); of the Eerste Kamer `ek-<slug>`."""
    kind: str | None = None
    """By its name, else `Commissie.Inhoudsopgave`."""
    started_on: str | None = None
    """`DatumActief`."""
    ended_on: str | None = None
    """`DatumInactief`."""
    active_dossier_count: int | None = None
    """The open dossiers it leads, none once dissolved (`semantic graph-list-stats`)."""
    chamber: str | None = None
    """`EK` for the Eerste Kamer (`normalize eerstekamer-composition`)."""
    url: str | None = None
    """Of the Eerste Kamer: its page on eerstekamer.nl."""
    retrieved_on: str | None = None
    """The day that page was read."""
    observed_from: str | None = None
    """The first day a snapshot showed it (not the day it began)."""
    observed_until: str | None = None
    """The first day a snapshot no longer did (not the day it ended)."""
    data_since: str | None = None
    """The day of the first snapshot of the Eerste Kamer."""
    title: str | None = None
    """The heading of its page: `Commissie voor Financiën (FIN)`."""


# ---------------------------------------------------------------------------
# members
# ---------------------------------------------------------------------------


class SourceRefProps(_StrictBase):
    """Where a cabinet or a post was read: ``rijksoverheid``, with the page and the day."""

    name: str | None = None
    """The source."""
    url: str | None = None
    """The page."""
    read_on: str | None = None
    """The day it was read."""


class PartyRefProps(_StrictBase):
    """A party as the source writes it (``VVD``, ``partijloos``), and its faction key."""

    short: str | None = None
    """As the source writes it."""
    faction: str | None = None
    """Its faction key."""


class GovernmentFunctionProps(_StrictBase):
    """A post held in a cabinet (``normalize rijksoverheid``, ``core.cabinet_posts``)."""

    cabinet_key: str | None = None
    """The cabinet node."""
    cabinet: str | None = None
    """Its name: "kabinet-Rutte IV"."""
    function: str | None = None
    """The post as the source writes it: "Minister van Infrastructuur en Waterstaat"."""
    also_named: list[str] | None = None
    """The other names of the post."""
    post: str | None = None
    """The normalised post (``core.ministries.POSTS``)."""
    ministry: str | None = None
    """The key of its ministry (``core.ministries.MINISTRIES``; ``core/post_ministries.py``)."""
    ministry_source: str | None = None
    """Where the ministry comes from: `page`, `tk_signatures`, `tk_commitments`,
    `staatscourant`."""
    ministry_missing: str | None = None
    """When `ministry` is null, why: `no_source`, `ambiguous`."""
    seat: str | None = None
    """`ienw/minister`, `-/staatssecretaris/rechtsbescherming`,
    `viceminister-president`."""
    portfolio: str | None = None
    """The portfolio."""
    from_date: str | None = None
    """The first day held."""
    to_date: str | None = None
    """The last day held; null while held."""
    from_date_source: str | None = None
    """The day the page gave, null when none."""
    to_date_source: str | None = None
    """Likewise."""
    corrected: list[str] | None = None
    """Which dates the rules of a seat set."""
    acting: bool | None = None
    """A stand-in (ad interim)."""
    acting_reason: str | None = None
    """`source` or `held_other_seat`."""
    acting_basis: str | None = None
    """The words of the page."""
    acting_other_seat: dict[str, str] | None = None
    """`{seat, function}` of the seat held besides."""
    party: PartyRefProps | None = None
    """The party of the holder."""
    overlaps_with: list[str] | None = None
    """Member keys holding the seat at the same time."""
    absent: list[str] | None = None
    """The periods of a "tijdelijk afwezig"."""
    name: str | None = None
    """The holder as the page writes them."""
    source: SourceRefProps | None = None
    """The page it was read from."""


class FactionMembershipProps(_StrictBase):
    """A period in a faction (``_tk_members.link_members_to_factions``; of the Eerste Kamer
    ``normalize eerstekamer-persons``, with ``chamber``)."""

    faction_id: str | None = None
    """The faction node."""
    faction_key: str | None = None
    """Its key."""
    name: str | None = None
    """Its name."""
    abbreviation: str | None = None
    """Its abbreviation."""
    aliases: list[str] | None = None
    """Its other names."""
    from_date: str | None = None
    """The first day."""
    to_date: str | None = None
    """The last day (`TotEnMet`); null while it lasts."""
    role: str | None = None
    """`FractieZetelPersoon.Functie`."""
    chamber: str | None = None
    """`EK` for the Eerste Kamer."""


class HallSeatProps(_StrictBase):
    """A place in the hall of the Eerste Kamer (``core.ek_composition.HallSeat``)."""

    block: str
    """The block of the hall."""
    row: int
    """The row in it."""
    column: int
    """The place in the row."""


class MemberEkProps(_StrictBase):
    """A seat in the Eerste Kamer (``normalize eerstekamer-composition``)."""

    name: str | None = None
    """As its page writes it."""
    path: str | None = None
    """The path of that page."""
    url: str | None = None
    """The page."""
    faction: str | None = None
    """The faction key."""
    abbreviation: str | None = None
    """The faction's abbreviation."""
    seniority_days: int | None = None
    """`Anciënniteit`: no start date."""
    residence: str | None = None
    """The place of residence, as the page gives it."""
    seat: HallSeatProps | None = None
    """Their place in the hall."""
    observed_from: str | None = None
    """The first day a snapshot showed the seat."""
    observed_until: str | None = None
    """The first day a snapshot no longer did."""
    retrieved_on: str | None = None
    """The day the page was read."""
    data_since: str | None = None
    """The day of the first snapshot of the Eerste Kamer."""


class MemberProps(_CommonProps):
    external_id: str | None = None
    """The id of its `Persoon` record."""
    name: str | None = None
    """The name they go by: `Persoon.Roepnaam` and the surname."""
    full_name: str | None = None
    """`Persoon.Voornamen` and the surname."""
    initials: str | None = None
    """`Persoon.Initialen`: "S.Th.M."."""
    party: str | None = None
    """The party."""
    faction_memberships: list[FactionMembershipProps] | None = None
    """Every period in a faction of the Tweede Kamer, with its dates."""
    ek_faction_memberships: list[FactionMembershipProps] | None = None
    """The periods in the factions of the Eerste Kamer, as their page says them (`normalize
    eerstekamer-persons`), in the shape of `faction_memberships`."""
    family_name: str | None = None
    """`Persoon.Achternaam`, without the tussenvoegsel."""
    name_prefix: str | None = None
    """`Persoon.Tussenvoegsel`: "van der"."""
    number: str | None = None
    """`Persoon.Nummer`."""
    slug: str | None = None
    """The name as the API gives it, lower-case ASCII with hyphens
    (``core/member_slugs.py``); given once and never changed; a later namesake gets the
    year they were born, else `number`, else a number of its own. `lawgraph check` fails
    on a slug two members share."""
    birth_date: str | None = None
    """The date of birth."""
    death_date: str | None = None
    """The date of death (`Overlijdensdatum`)."""
    government_name: str | None = None
    """As Rijksoverheid writes it: "S.Th.M. Hermans"."""
    known_as: str | None = None
    """"Sophie Hermans": the first name Rijksoverheid gives; null when none."""
    government_functions: list[GovernmentFunctionProps] | None = None
    """Every post in a cabinet since 1945, oldest first (`normalize rijksoverheid`)."""
    ek: MemberEkProps | None = None
    """A member of the Eerste Kamer."""


# ---------------------------------------------------------------------------
# cabinets
# ---------------------------------------------------------------------------


class CabinetPhaseProps(_StrictBase):
    """A phase of a cabinet (``core.cabinet_phases``)."""

    kind: str | None = None
    """`formatie`, `in_functie`, `demissionair`, `dubbel_demissionair`, `missionair`; null:
    unknown."""
    from_date: str | None = None
    """The first day."""
    to_date: str | None = None
    """The last day."""
    label: str | None = None
    """The source's own words."""
    source: SourceRefProps | None = None
    """Where it was read."""


class CabinetProps(_CommonProps):
    name: str | None = None
    """`kabinet-Rutte IV`."""
    from_date: str | None = None
    """The beëdiging."""
    to_date: str | None = None
    """The last day; null while in office."""
    prime_minister: str | None = None
    """The member key of its prime minister."""
    previous: str | None = None
    """The key of the cabinet before it."""
    parties: list[PartyRefProps] | None = None
    """The parties of the bewindspersonen sworn in on the first day."""
    factions: list[str] | None = None
    """The faction keys of its parties."""
    phases: list[CabinetPhaseProps] | None = None
    """Its phases."""
    demissionary_from: str | None = None
    """The day it went demissionary."""
    origin: SourceRefProps | None = None
    """The page or the record it was read from."""


# ---------------------------------------------------------------------------
# factions
# ---------------------------------------------------------------------------


class PeriodProps(_StrictBase):
    """A period, both days inclusive; ``to_date`` None while it lasts."""

    from_date: str
    """The first day."""
    to_date: str | None = None
    """The last day; null while it lasts."""


class FactionBoardSeatProps(_StrictBase):
    """A seat on the board of a faction of the Eerste Kamer, as its page gives it."""

    function: str
    """The function."""
    name: str
    """The holder, as the page writes them."""
    member: str | None = None
    """The member key."""
    since: str | None = None
    """The day they hold it from."""


class FactionProps(_CommonProps):
    external_id: str | None = None
    """The current Fractie record."""
    external_ids: list[str] | None = None
    """Every Fractie record of the faction: one that returns gets a new record, and votes
    and seats name either."""
    name: str | None = None
    """Its name; of the Eerste Kamer the heading of its page (`D66-fractie`)."""
    abbreviation: str | None = None
    """Its abbreviation; the key is made from it, else from the name."""
    aliases: list[str] | None = None
    """Its other names."""
    active_from: str | None = None
    """The first day its seats were held, where the seats date it (from 30 November 2006);
    else the Fractie record's."""
    active_until: str | None = None
    """The last day, likewise."""
    seats: int | None = None
    """`AantalZetels` (0 once the faction has ended); of the Eerste Kamer as `/fracties`
    lists them."""
    seats_changed_on: str | None = None
    """The day one of its seats last changed (`FractieZetel.GewijzigdOp`)."""
    vacancies: list[PeriodProps] | None = None
    """The periods a seat of it was held by no member (`FractieZetelVacature`): only the
    days no member held that seat (a seat is held or vacant, never both); both days
    inclusive, the last the one before the successor took it. `/api/cabinets/{key}/seats`
    counts them among its seats."""
    active: bool | None = None
    """A Fractie record of it has no end (`DatumInactief`); of the Eerste Kamer: the latest
    snapshot shows it."""
    chamber: str | None = None
    """`EK` for the Eerste Kamer (`normalize eerstekamer-composition`)."""
    url: str | None = None
    """Of the Eerste Kamer: its page on eerstekamer.nl."""
    retrieved_on: str | None = None
    """The day that page was read."""
    observed_from: str | None = None
    """The first day a snapshot showed it (not the day it began)."""
    observed_until: str | None = None
    """The first day a snapshot no longer did (not the day it ended)."""
    data_since: str | None = None
    """The day of the first snapshot of the Eerste Kamer."""
    board: list[FactionBoardSeatProps] | None = None
    """Its board, as the page gives it."""


# ---------------------------------------------------------------------------
# cases (TK Zaken)
# ---------------------------------------------------------------------------


class RelatedCase(_StrictBase):
    id: str
    """The TK id of the case."""
    kind: str | None = None
    """Its `Zaak.Soort`."""
    dossier_numbers: list[str] = []
    """Its dossiers."""


class CaseProps(_CommonProps):
    external_id: str | None = None
    """The id of its `Zaak` record."""
    title: str | None = None
    """`Zaak.Titel`; of a motie, amendement, letter or report its `Onderwerp` (its `Titel`
    is its dossier's)."""
    citation_title: str | None = None
    """As the Kamer writes it."""
    number: str | None = None
    """As the Kamer writes it."""
    kind: str | None = None
    """`Zaak.Soort`: `Wetgeving`, `Motie`, `Brief regering`, ..."""
    dossier_numbers: list[str] | None = None
    """Its dossiers."""
    started_on: str | None = None
    """`Zaak.GestartOp`."""
    related_cases: list[RelatedCase] | None = None
    """`Zaak.GerelateerdNaar`: each case the Kamer relates it to (read by `semantic
    tk-dossier-relations`)."""
    replaces_cases: list[str] | None = None
    """`Zaak.VervangenVanuit`: the TK ids of the cases this one replaces ("ter vervanging
    van nr. 21")."""
    done: bool | None = None
    """`Zaak.Afgedaan`: whether the Kamer is done with it. An amendment or motion done
    with and without a decision was replaced or withdrawn; one not done with is still
    open."""


# ---------------------------------------------------------------------------
# annexes
# ---------------------------------------------------------------------------


class AnnexEntry(_StrictBase):
    index: int | None = None
    """Its place in the list."""
    name: str | None = None
    """Its name."""
    description: str | None = None
    """Its description."""
    heading: str | None = None
    """The paragraph introducing its list: "Gemeentewet"."""
    parent_index: int | None = None
    """The entry it is nested in."""


class AnnexProps(_CommonProps):
    bwb_id: str | None = None
    """The BWB id of its regulation."""
    label: str | None = None
    """`I`, `2`, `A`: as cited in article text."""
    title: str | None = None
    """The title of its heading; absent where it prints none."""
    position: int | None = None
    """Its place among the annexes of the toestand: the order of the table of contents."""
    description: str | None = None
    """Its paragraphs outside its lists, a line each, cut at 2,000 characters."""
    entries: list[AnnexEntry] | None = None
    """Its list."""
    text: str | None = None
    """Its text as that of an article, without its articles (articles of their own): a
    paragraph a line, list items on their own lines, a table a row a line, the heading of a
    division on a line of its own."""
    parts: list[dict[str, Any]] | None = None
    """The structure of its text, as of an article: `{id, kind, number, start, end, term}`."""
    tables: list[dict[str, Any]] | None = None
    """The tables in its text, as of an article: `{start, end, head_rows, columns, spans}`."""
    headings: list[dict[str, Any]] | None = None
    """The headings in its text (of a division, a table), as of an article: `{start, end}`."""
    footnote_marks: list[dict[str, Any]] | None = None
    """Where the markers of its footnotes stood in its text, as of an article: `{at, number}`."""
    footnotes: list[dict[str, Any]] | None = None
    """Its `<noot>` footnotes, not in its text, as of an article: `{number, text}`."""
    references: list[dict[str, Any]] | None = None
    """The links of its text to a regulation, an annex or an EU act, as of an article."""
    instrument_id: str | None = None
    """Its instrument."""
    instrument_citation_title: str | None = None
    """The citation title of its law, which its title cites (`Bijlage 1 Awb`; `normalize
    bwb` keeps it in step with the instrument)."""
    instrument_abbreviation: str | None = None
    """The abbreviation of its law, likewise."""

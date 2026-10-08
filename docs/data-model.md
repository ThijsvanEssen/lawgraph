# Data model

The graph is a set of document collections (nodes) and one edge collection (`edges`).
Concepts, collections, relations and property names are English throughout; Dutch appears only
in values that a source owns (a document `kind` such as `memorie van toelichting`, an edge
`status` such as `voorgesteld`).

## Nodes

A node is a document `{_key, type, labels, props}`:

- `_key` is deterministic (`make_node_key(...)`: parts joined with `_`, lower-cased, ASCII,
  non-alphanumerics replaced by `_`), so every pipeline can be re-run.
- `type` is the `NodeType` (`instrument`, `article`, `instrument_version`, `article_version`,
  `annex`, `judgment`, `dossier`, `case`, `document`, `activity`, `decision`, `commitment`,
  `member`, `faction`, `committee`, `cabinet`). Every type has its own collection and every
  collection holds one type (`core.models.COLLECTION_OF_TYPE`), so the collection in an id
  says the type.
- `labels` tag the origin (`BWB`, `EU`, `TK`, `Rechtspraak`, `ECHR`, `EersteKamer`, ...). Upserts
  union labels.
- `props` of a node built as a `Node` are validated against the strict Pydantic schema of its
  collection (`core/props.py`); an unknown field is rejected. Upserts merge props (shallow), so
  several pipelines can add fields to one node.
- `display_name` is the name to show. A name longer than its limit (a paper's title 120
  characters, a commitment 80, a Staatscourant title 100, other titles `MAX_TITLE_CHARS`) is cut
  with an ellipsis (`core/display.shorten`) at the last word boundary, or at the limit when
  that boundary lies in the first half; the full title stays in `title`.
- `stub: true` marks a placeholder created because something referred to it before its own
  source was ingested. A stub judgment has a valid ECLI (`core/ecli.is_valid_ecli`) and an edge
  at it; `semantic rechtspraak-citations` removes one that has none.

Other collections: `raw_sources` (the records as fetched, their XML and HTML in the payload
store) and `pipeline_state`: per phase when its last complete `<phase> all` began (for
`--since last`), where a long retrieve broke off (`retrieve eerstekamer-agenda`), and the marks
of `lawgraph bootstrap` (`bootstrap <step>`). `lg_heat` keeps the heat of the whole graph (`semantic
graph-heat`): per window of 3, 6, 12 and 24 months the 50,000 nodes with the highest count, and
`lg_heat_state` when it was counted; writing them raises no data version. `lg_judgment_light` holds per
judgment what a neighbour, a node of a neighbourhood or of a path shows of it (its ecli, names,
summary to 401 characters, date, court, case number, source, jurisdiction, stub, translation
and advocate-general), kept by triggers on every write of `judgments` and filled once by
`semantic graph-light`; it raises no data version either. `lg_document_light` holds per paper
what the signals of its dossier read (`schema.DOCUMENT_LIGHT_PROPS`: kind, date, titles,
dossier numbers, case kinds, sequence), without its text, kept and filled the same way from
`documents`.

## Node types and relation catalogue

The tables below are generated from `src/lawgraph/core/relations.py`, which holds the whole
vocabulary: `config/constants.py` has exactly one `RELATION_*` constant per entry and no other
relation name exists. Refresh them with `python -m lawgraph.core.relations`; a test fails when
they are out of date. Do not edit inside the markers.

<!-- relations:begin (generated: python -m lawgraph.core.relations) -->

| Node type | Collection |
|-----------|-----------|
| Instrument | `instruments` |
| InstrumentVersion | `instrument_versions` |
| Article | `articles` |
| ArticleVersion | `article_versions` |
| Annex | `annexes` |
| Judgment | `judgments` |
| Dossier | `dossiers` |
| Case | `cases` |
| Document | `documents` |
| Activity | `activities` |
| Decision | `decisions` |
| Commitment | `commitments` |
| Member | `members` |
| Faction | `factions` |
| Cabinet | `cabinets` |
| Committee | `committees` |

| Relation | From | To | Meaning |
|----------|------|----|---------|
| `PART_OF` | Article / Annex / Document / Case / Instrument | Instrument / Case / Dossier | Containment. Article/Annex → Instrument; Document → Case or Dossier; Case → Dossier; a treaty → the treaty it belongs to, as the Verdragenbank registers it (a Protocol → its Convention, `Moederverdrag`). |
| `VERSION_OF` | InstrumentVersion / ArticleVersion | Instrument / Article | A dated version of an instrument or article. An article keeps one identity across versions (BWB `stam-id`); each version has valid_from / valid_until. |
| `AMENDS` | Instrument / Document | Instrument / Article | An instrument changes existing text (effective date and version in `meta`). A bill (Document) proposing the change carries status `voorgesteld`. |
| `INTRODUCES` | Instrument / Document | Instrument / Article | An instrument adds a new article or instrument; a bill proposing it is `voorgesteld`. |
| `REPEALS` | Instrument / Document | Instrument / Article | An instrument withdraws an article or instrument; a bill proposing it is `voorgesteld`. |
| `BASED_ON` | Instrument | Article | The legal basis (delegation basis) an instrument is issued under: 'Gelet op artikel …' in the preamble. |
| `IMPLEMENTS` | Instrument | Instrument | A national instrument implements an EU act, by an implementation source (`meta.bases`): a publication EUR-Lex lists as a national implementing measure of the act, and the regulations it enacted or changed (`national_implementing_measure`, `meta.publications`, and `meta.measures`: each with `citation`, and `title` and `type` as EUR-Lex gives them), or a regulation whose considerans says it implements the act (`considerans`). Not per article: no source names the implementing article. |
| `LEGISLATED_IN` | Instrument | Dossier | The parliamentary dossier in which an instrument was legislated (BWB `dossierref`), or in which a treaty was approved (the Verdragenbank's `Kamerstukken`, `meta.rijks_number`). |
| `PUBLISHED_IN` | Instrument | Instrument | A treaty → a Tractatenblad that publishes it or something about it, as the Verdragenbank registers it: its text, its approval, its entry into force, its parties (`meta.description`, as the register writes it). |
| `REFERS_TO` | Article / Document / Judgment / Instrument | Article / Instrument / Judgment | A text refers to an article, instrument or judgment: the reference is in the text, never only in metadata (a judgment's earlier instance or conclusion is `APPEAL_OF` or `ADVISES_ON`), and two judgments of one case tied by `APPEAL_OF`, `CONTINUES`, `REFERRED_BY`, `ADVISES_ON` or `ANSWERS` have that edge only. The source node says who refers; article → article edges also carry a `semantic_type`. From an instrument: a regulation whose text names the CELEX number of an EU act it does not `IMPLEMENTS`. |
| `EXPLAINS` | Document | ArticleVersion / Article / Instrument | A document (MvT, NvT) explains the article version or instrument it introduced or changed. Written per dossier: every MvT and NvT of a dossier explains everything its law changed; an MvT edge carries `meta.section_anchor` when one of its sections is about that article. |
| `APPEAL_OF` | Judgment | Judgment | An appeal or cassation judgment → the judgment it appeals: an earlier instance its metadata names (`meta.basis` `formal_relation`), else the decision its text says it appeals, by date and case number (`appeal_text`). |
| `CONTINUES` | Judgment | Judgment | A judgment → an earlier one of the same court in the same case (an interim judgment followed by the final one): an earlier instance its metadata names that shares its court and case number. |
| `REFERRED_BY` | Judgment | Judgment | A decision after referral (verwijzing) → the ruling of the Hoge Raad that set aside the earlier decision and sent the case to it: an earlier instance its metadata names that is a Hoge Raad ruling (not a preliminary ruling). |
| `ADVISES_ON` | Judgment | Judgment | The conclusion of an advocate-general (Parket bij de Hoge Raad, or of the court itself) → the judgment in its case, one way only: the formal relation of either, when the side it calls the conclusion is one (`meta.basis` `formal_relation`), else a case number the two share (`case_number`). |
| `ANSWERS` | Judgment / Document | Judgment / Commitment | A preliminary ruling (prejudiciële beslissing) → the decision that asked its questions: the earlier instance its metadata names (`meta.basis` `formal_relation`), else the ECLI or the case number and date its text names (`referral_text`). A letter → the commitment it fulfils (`Toezegging.KamerbriefNakoming`). |
| `SAME_AS` | Judgment | Judgment | A publication of a decision → the publication of the same decision that replaces it (an old arrest published again under a new ECLI): the ECLI its metadata names as `dcterms:isReplacedBy`. The lists show the decision once, by the one kept. |
| `SCOPED_BY` | Article | Annex | An article whose scope is defined by an annex. |
| `ABOUT` | Activity / Decision / Commitment | Case / Dossier | The subject of an activity, decision or commitment: Activity/Decision → Case; Commitment → Dossier. |
| `LED_BY` | Activity | Committee | The lead committee (`voortouwcommissie`) of an activity; absent for plenary. |
| `MADE_IN` | Commitment / Document | Activity | The activity in which a commitment (toezegging) was made, or of which a document is the record (a stenogram of its debate: `Document.Activiteit`). |
| `MEMBER_OF` | Member | Committee / Faction | Membership of a committee or faction, with from/to dates and role. |
| `SERVED_IN` | Member | Cabinet | The posts a member held in a cabinet, one edge per member and cabinet, `meta.posts` as in the member's `government_functions`. |
| `AUTHORED` | Member | Document / Case | A person signed or submitted a document or case; `role` says how (first signatory, co-signatory, …), `function` as what (`Functie`) and `capacity` in which capacity (`kamerlid`, `bewindspersoon`, `overig`). |
| `RELATED_TO` | Dossier / Judgment | Dossier / Judgment | Dossier → dossier: the Kamer relates a case of this dossier to a case of the other (`Zaak.GerelateerdNaar`), mostly a letter of the government to the motion it answers; `meta.cases` counts the pairs of cases, `meta.case_kinds` names them. Judgment → judgment: its summary names the other as a connected case, "Samenhang met 24/03860 E", "Zie ook: ECLI:NL:GHDHA:2025:1539" (`meta.basis` `summary_text`, `meta.text` the sentence as written); only on an exact match of the ECLI, or of the case number among the judgments of the same court (the Hoge Raad's type letter is not part of the comparison). |
| `REVISES` | Dossier | Dossier | A supplementary budget or a slotwet revises the budget of its chapter and year (`meta.rule`: `begrotingswijziging` or `slotwet`). |
| `ACCOMPANIES` | Dossier / Document | Dossier / Document | A budget change is submitted with the Voorjaarsnota, Najaarsnota or Miljoenennota (`meta.nota`) that its title names (Dossier → Dossier); an attachment is sent with its letter (Document → Document: `BijlageDocument`). |
| `SECOND_READING_OF` | Dossier | Dossier | A change in the Grondwet in its second reading → the dossier of its first reading, to whose papers its memorandum refers for the explanation (Kamerstukken 35 418). |
| `VOTED` | Member / Faction | Decision | A vote on a decision: per member for roll-call votes, per faction otherwise (`choice`, `seats`). |

<!-- relations:end -->

## Keys

| Collection | Key |
|------------|-----|
| `instruments` (BWB) | `bwbr0001854` (`bwb_id`; treaties `bwbv...`) |
| `instruments` (EU) | `32016l0680` (`celex`) |
| `instruments` (Verdragenbank treaty) | `verdrag_<id>` |
| `instruments` (amending publication) | `stb_2019_33` (publication identifier) |
| `articles` | `<bwb_id>_<article_number>` (a book of the Burgerlijk Wetboek is a regulation of its own: `bwbr0005289_162` is 6:162 BW; an article of an annex `bwbr0005537_bijlage_2_artikel_9`; an article without a number `<bwb_id>_stam_<stam_id>`: `bwbr0001840_stam_16464063`); EU `<celex>_<article_number>`; historical `<bwb_id>_<number>_stam_<stam_id>` |
| `instrument_versions` | `<bwb_id>_<valid_from>` |
| `article_versions` | `<bwb_id>_av_<stam_id>_<versie_id>` |
| `annexes` | `<bwb_id>_annex_<label>` (`<bwb_id>_annex` without a label) |
| `judgments` | `ecli_nl_hr_2023_1234`; ECHR its ECLI, else `echr_<itemid>` |
| `dossiers` | `<number>` or `<number>_<suffix>` |
| `cases`, `documents` (TK), `activities`, `commitments`, `committees`, `members` | TK GUID (`Id`); a bewindspersoon only Rijksoverheid knows `rijksoverheid_<initials>_<surname>` |
| `documents` (other) | `stb_<identifier>`, `stcrt_<identifier>`, `ek_<id>` |
| `decisions` | `decision_<Besluit_Id>`; Eerste Kamer `ek_<date>_<label>_<n>` |
| `factions` | abbreviation, else name (`vvd`, `d66`) |
| `edges` | `SHA-1(_from:relation:_to)`: one edge per (from, relation, to) |
| `raw_sources` | `SHA-1(source:kind:external_id)`; random UUID when `external_id` is null |

## Edge document

| Field | Meaning |
|-------|---------|
| `_from`, `_to` | node ids (`collection/key`) |
| `relation` | a catalogue name |
| `source` | the pipeline that wrote the edge (`bwb-amendments`, `tk-article-linker`, ...) |
| `status` | `canoniek` (default) or `voorgesteld` — a change a bill proposes but has not enacted, written by `tk-amendment-articles` and by `tk-amends` |
| `confidence` | 0-1; absent on structural edges; 1.0 when read from source XML |
| `created_at` | set on insert only |
| `meta` | evidence and context: `start`, `end`, `text`, `raw_match`, `snippet` (300 characters around the match), `reason`, `qualifier`, `reference_kind`, `leden`, `onderdelen`, `aanhef`, `mentions`, `mention_count`, `effective_date`, `article_version`, `scope_type`, ... Upserts merge `meta` |

An edge is one per (`_from`, `relation`, `_to`); a second write replaces `source`, `status` and
`confidence` and merges `meta`. `EXPLAINS` from a memorandum has two writers that share its
key: `semantic tk-mvt` (a change of the dossier, `confidence` 0.5, no section) and `semantic
tk-mvt-articles` (a section that is about the article; `source` `mvt-section-linker`, the
`confidence` of the surest section). The second wins whichever ran first. Its `meta`:

| Field | Meaning |
|-------|---------|
| `section_anchor` | `id` of the surest section (`props.sections` of the Document); `heading`, `char_start`, `char_end`, `match_type`, `changed` and `explanation` are that section's |
| `match_type` | `heading_target`, `body_named_law`, `own_number` or `inferred_law` (`docs/pipelines.md`) |
| `changed` | whether the dossier changed the article, which corroborates the match |
| `explanation` | what the match rests on, in Dutch |
| `sections` | every section that explains the article, in document order: `section_anchor`, `heading`, `char_start`, `char_end`, `match_type`, `changed`, `confidence`, `explanation` |

`char_start`/`char_end` are offsets into `props.text` of the Document.

Semantic layer on article-to-article `REFERS_TO` edges, orthogonal to `relation`: `relation`
says that two articles are linked, `semantic_type` says what the link means.

| Field | Values |
|-------|--------|
| `semantic_type` | `conditional_requirement`, `scope_limitation`, `prerequisite_procedure`, `definitional_reference`, `limiting_exception`, `cross_reference`, `delegated_discretion`; null for unclassified edges |
| `explanation` | the phrase that decided the type and where it stood, in words |
| `updated_at` | when the classification last changed |
| `meta.semantic_pattern` | the pattern and where its phrase stood: `limiting_exception_adjacent`, `definitional_reference_window`, `cross_reference_fallback` |
| `meta.semantic_confidence` | the share of classifications by that pattern a hand check found right ([per pattern](pipelines.md#bwb-dutch-legislation)); the edge's `confidence` (1.0) is that the reference exists |
| `meta.linked_article` | the key of the article the link of the XML points at, when the words of the reference name another (`semantic bwb`) |

## Instrument

An instrument is any rule with a basis in a power laid down in law. It is not limited to
statutes made by the legislator:

- BWB types ingested (`BWB_INSTRUMENT_TYPES`): `wet`, `rijkswet`, `AMvB`, `rijksAMvB`, `KB`,
  `rijksKB`, `ministeriele-regeling`, `ministeriele-regeling-archiefselectielijst`, `zbo`,
  `pbo`, `reglement`, `beleidsregel`, `verdrag`, and the `-BES` variants of `wet`, `AMvB`,
  `ministeriele-regeling` and `beleidsregel`. `circulaire` is not ingested.
- A BWB regulation also carries what its toestand says other steps link from: `basis` (the
  `Gelet op` references: `bwb_id`, `article`, `doc`, `text`), `celex_refs` (the EU acts its
  text names) and `implements_celex` (the EU acts its considerans says it implements);
  `retrieve eurlex --mode gaps` fetches the acts of `celex_refs` and `implements_celex`.
  `enacted_publication` is the publication that enacted it (`stb-2018-144`). Its `title` is the
  citeertitel, else the intitule; `kind` is `wetgeving@soort`. `date_signed`, `date_published`
  and `dossier_numbers` are those of that publication, `date_in_force` the
  `inwerkingtreding.datum` of the `<intitule>` (each null or empty when the toestand does not say
  it): the `meta-data` of `<wetgeving>` names the last change to the structure of the law, not
  the law. `version_date_in_force` is the start of the toestand. A Celex link
  whose id has an impossible year in the source is rebuilt from the text of the link
  ("verordening (EU) 2021/784") or left out.
- Treaties are instruments, both BWB treaties (`BWBV...`) and Verdragenbank records
  (`verdrag_<id>`), two nodes for a treaty that is in both. They share `treaty_number`, the
  six-digit Verdragenbank id, which a BWB treaty names in `wetgeving@verdragnummer`; no edge
  joins them (see [pipelines](pipelines.md#verdragenbank)). A Verdragenbank treaty also
  carries what its item XML registers: `place_signed`, `tractatenblad` (`official_id`,
  `text`, `description`), `parties` (`name` and its dates, `consent`, `reservation`,
  `objection`), `kingdom_parts`, `kamerstukken` and `parent_treaties`/`child_treaties`
  (Verdragenbank `id`, `title`, `date`, `place`).
- EU directives, regulations and decisions (`celex`). `title` is the printed title
  (`Verordening (EU) 2022/868 van het Europees Parlement en de Raad van 30 mei 2022
  betreffende …`), `citation_title` the form the act is cited by in its era (`Richtlijn
  87/102/EEG`, `Richtlijn 95/46/EG`, `Verordening (EU) nr. 1093/2010`, `Verordening (EU)
  2016/679`), `short_title` the name between brackets that ends the title
  (`Datagovernanceverordening`), `display_name` the citation title.
- The Convention of the ECHR is the BWB treaty `BWBV0001000` (`bwbv0001000`, articles
  `bwbv0001000_<n>`), abbreviated `EVRM` in its WTI; ECHR judgments cite its articles.
- `legal_areas` and `policy_domains` of a BWB regulation are how its WTI files it: `{main,
  main_id, main_uri, main_slug, specific, specific_id, specific_uri, specific_slug}` per legal
  area ("Staats- en bestuursrecht", "Bestuursrecht") and `{label, id, uri, slug}` per
  government theme ("Overheid, bestuur en koninkrijk"), the ids and URIs those of the TOOI
  concepts (`scw_bwb_rechtsgebieden`, `scw_bwb_themas`), the slugs unique in their list.
  Written by `normalize bwb`; `lg_legal_area_keys` and `lg_policy_domain_keys` (GIN indexes)
  are what `/api/instruments` filters on.
- `abbreviation` of an instrument is the abbreviation it is cited by
  (`core.aliases.abbreviation_of`): the WTI short title of a BWB regulation or treaty
  (`EVRM`), else the first one kept by hand (`curated instrument-abbreviations`: `AVG` for
  `32016R0679`). Its articles carry it as `instrument_abbreviation` (`art. 8 EVRM`). Written
  by `normalize bwb`.
- Amending publications (Staatsblad, Tractatenblad, ...) are instruments too, of `kind`
  `publicatie` (`publication_kind`, `publication_year`, `publication_number`, `date_signed`,
  `date_published`, `dossier_numbers`; `citation_title` is their name, `Stb. 2019, 33`); they
  are the source of `AMENDS`, `INTRODUCES` and `REPEALS`, and no regulation: the instrument
  lists and `/api/stats` keep them apart.
- `official_title` is the `intitule` of its toestand, `citation_title` the title it is cited
  by. `semantic graph-list-stats` writes `jurisdiction` (`nl` with a `bwb_id`, `eu` with a
  `celex`), `article_count` (the articles `PART_OF` it, not its annexes) and
  `inbound_citation_count` (the `REFERS_TO` edges to it and to its articles), which the lists
  sort and filter on.

An instrument that amends, introduces or repeals has enacted the change (`status: canoniek`).
A bill (Document) carries the same three relations with `status: voorgesteld` — a change it
proposes. Only an instrument is based on a basis article or implements a directive, and only a
document (memorie van toelichting, nota van toelichting) explains.

## Article and versions

BWB identifies an article by `stam-id`, which stays the same across versions and
renumbering; each version has a `versie-id`.

| Node | Identity | Notes |
|------|----------|-------|
| Article | one per `(bwb_id, article_number)` for the current text, per `stam_id` for an article without a number; historical identities per `stam_id` | props: `label` (`Artikel 287`, or the heading of an article without a number: `Algemene bepaling`), `heading` (the `<titel>` of its `<kop>`, numbered or not: `Definities`; absent when the BWB prints none, as for every article of the Wetboek van Strafrecht and the Burgerlijk Wetboek), `position` (its place in the current toestand: the order of the lists), `text` (a lid as `1. text`, list items on their own lines, a paragraph beside the leden included), `stam_id`, `versie_id`, `valid_from` (`inwerking`), `source_publication` (`bron`), `repealed`, `parts`, `references`, `breadcrumb` (see below) |
| ArticleVersion | one per `(stam_id, versie_id)`, not per toestand; a republication (`tekstplaatsing`) with the label, heading, place and text (`content_digest`) of the version before it is that version | `label`, `heading`, `position` (its place in one order of all versions of the law in which the versions of every toestand keep theirs), `breadcrumb` (the divisions of the first toestand holding it) and `breadcrumb_changes` (`[{from, breadcrumb}]`, oldest first: the toestand starts from which it stood under other divisions, as when a hoofdstuk is renamed; null for most); `valid_from` = the article's own `inwerking`; `valid_until` = `valid_from` of the next version of the same article (the first day it no longer holds; its own `valid_from` for a version that says the article lapsed; the start of the first toestand without it for an article that left the law), null when current; `current`; `last_seen` (the start of the latest toestand holding it); `effect` (`nieuw`, `wijziging`, `vervallen`, ...); `source_publication`; `parts`; `origin_publication` and `commencement_publication` (id, kind, year, number, effect, signed, published, dossiers) |
| InstrumentVersion | one per toestand `(bwb_id, valid_from)` | `valid_from`, `valid_until` (exclusive: the day after the toestand's last day; null when open), `current`, `state_url` |

- `ArticleVersion VERSION_OF Article` and `InstrumentVersion VERSION_OF Instrument`. There are
  no membership or succession edges: "the article on date X" is the version with
  `valid_from <= X` and (`valid_until > X` or null).
- An annex (`<bijlage>`) numbers its articles on its own: Bijlage 2 and Bijlage 3 of the Awb
  each have an article 1. The number of an article of an annex names the annex as the JCI does
  (`bijlage=2&artikel=9`): `article_number` is `bijlage 2 artikel 9`, its display name
  `Artikel 9 van bijlage 2 …`, and a reference to it (`props.references`) has that number.
- An article may have a heading and no number (`<kop><titel>Algemene bepaling</titel></kop>`,
  the first article of the Grondwet; the Slotbepaling of BW Boek 8). It is an article like any
  other, with its text and parts, keyed and addressed by its `stam-id`, which stays across
  versions: `article_number` is null, `label` its heading, `display_name` `Algemene bepaling
  Grondwet`. No prop ever holds the text `None`.
- Historical articles are identities that are not in the current toestand. They have no
  `article_number` (`(bwb_id, article_number)` is a unique index); the last known number is
  in `last_article_number` and their `label` is that of their newest version. They carry
  `repealed: true`.
- `repealed` is also set on a current article whose latest `effect` is `vervallen`, and is
  `false` on every other current article: it is never read from the number.
- Articles of the current toestand without text, or without a number and a `stam-id`, are not
  written.
- `parts` is the structure of the text: a list of `{id, kind, number, start, end}`, offsets into
  the article's own `text` (the text of a part is `text[start:end]`, without its printed
  number). `kind` is `lid`, `onderdeel`, `aanhef` or `tekst`; sentences (volzinnen) are not parts. A
  part with onderdelen spans them too, and the list is ordered by `start`, an enclosing part
  first. The `id` is stable and unique in the article: `lid-2`, `lid-2a`, `lid-2-aanhef` (the
  text of a lid before its onderdelen), `lid-2-onder-a`, `lid-2-onder-a-onder-1` (an onderdeel
  of an onderdeel), and for an article without leden `aanhef` and `onder-a`. Numbers are
  written lower case without the degree sign (`1°` is `onder-1`; `number` keeps `1°`). An
  item without a letter or digit (a dash, a definition) is `onder-_<n>`, its position among
  its siblings; a marker that repeats one before it gets `_<n>`, its occurrence
  (`onder-a_2`). In an article with parts, a paragraph in none of them (a note next to the
  leden, a line between the lists of an article of a bijlage) is a `tekst` (`tekst-1`,
  `tekst-2`), so that the parts and their printed numbers cover the whole text.
- An EU article (`celex`, `article_number`) has the same `heading`, `text` and `parts`, read
  from the CELLAR HTML (`core/eurlex_html.py`): `heading` is the line under "Artikel N"
  (`Onderwerp en toepassingsgebied`; null when the act prints none), a lid is `1. text`, a
  point is a line of its own that starts with its marker as printed (`a) text`, `i) text`,
  `— text`); `number` is the marker without its punctuation (`a`). A point laid out without
  text of its own shares its line with the first point inside it (`f) — de ontbinding`).
  Its `position` is its place in the act and its `breadcrumb` the divisions of the act
  (`hoofdstuk`, `afdeling`, `titel`, `deel`, `onderafdeling`: the first word of the label,
  written `Hoofdstuk III`, the title as printed). An EU article has no `label`, `references`
  or versions.
- `breadcrumb` is where the article stands in its regulation, outermost first:
  `{type, label, title}` per division that holds it, `type` the element of the toestand
  (`bijlage`, `boek`, `deel`, `titeldeel`, `hoofdstuk`, `afdeling`, `paragraaf`, `sub-paragraaf`,
  `divisie`), `label` as printed (`Hoofdstuk 1`, `Titel 1.1`), `title` its heading. Absent for
  an article outside every division.
- `inbound_citation_count` of an article (`semantic graph-list-stats`): its `REFERS_TO` and
  `EXPLAINS` edges in.
- An annex (`annexes`, `normalize bwb`, `PART_OF` its instrument) has `bwb_id`, `label` (`I`,
  `2`, `A`: as cited in article text), `title`, `description`, `instrument_id` and `entries`,
  its list: `{index, name, description, heading, parent_index}` (`heading` the paragraph that
  introduces a list, `parent_index` the entry it is nested in).
- `references` holds every `extref`/`intref` of the text that names a regulation:
  `{kind, bwb_id, article, doc, text, start, end, leden, onderdelen, aanhef}`. The `doc` (JCI)
  of a BWB link stops at the article, so `leden`, `onderdelen` (written as in the part ids)
  and `aanhef` are read from the text of the link (`core/qualifiers.py`); a link to a chapter
  or a title has none.

## Judgment

A Rechtspraak judgment carries:

- its header: `court`, `date`, `case_number`, and `judgment_metadata` with `type`, the
  procedure, `document_type` (`Uitspraak` or `Conclusie`), `related_eclis` (earlier
  instances), `later_eclis` (later instances: `psi:aanleg` latereAanleg), `conclusion_eclis` (its conclusion, or the judgment of a conclusion) and
  `subjects`;
- derived from it: `court_code`, `tier` (the `Type` of its court in the Instanties list),
  `court_kind` (the kind of court within it), `date_eff` and `case_number_keys` (the case
  numbers as compared); see [Courts](pipelines.md#courts);
- `published_on`, "Datum publicatie": the `dcterms:issued` of the `rdf:Description` about the
  published document (its `rdf:about` is the deeplink), not that of the ECLI's own
  description; null without the document. A column, the date of the feed;
- `source` (`rechtspraak`, or `echr` for an ECHR judgment), a column of the indexes of the
  judgment list;
- `summary`, `text`, `paragraphs`, `parties`, `decision_kind` and `names`; a conclusion also
  `advocate_general` and `advocate_general_role`.

An ECHR judgment carries `appno`, `title`, `date`, `respondent`, `originating_body`,
`articles`, `conclusion`, `importance` and, from the DOCX of its English item (else its French
one), `text` and `paragraphs`. Its paragraphs are read from the Word styles of the Court's
templates (`core/echr_docx.py`): `heading` for a section heading (`JuHHead`, `OpiHHead`,
`ECHRHeading1`), `subheading` for the levels below it (`JuHIRoman`, `JuHA`, `JuH1`,
`ECHRHeading2`…, and the cover lines styled so), `body` for the rest; a table of contents is left
out. A paragraph of the Court opens with its number ("12.  The applicant …"), cited as § 12:
`id` `par-12`, `number` `12`, the number not in `text` (not for a quotation or a point of the
operative part). A heading's number is read only where it is text ("I.  THE CIRCUMSTANCES",
`kop-i`); newer templates number headings by Word's list numbering, which the body does not
hold. A separate opinion numbers from 1 again (`par-1_2`). A paragraph without a number is
named by its text, as for a Rechtspraak judgment (`p-3f2a9c1e`). `text` is every paragraph as
printed, a blank line between.

`summary` is the inhoudsindicatie, in Dutch; null for a placeholder ("kopje volgt", "-", empty). The Rechtspraak publishes a few judgments in an
English translation too, under an ECLI of their own (ECLI:NL:HR:2019:2007 beside
ECLI:NL:HR:2019:2006, case number `19/00135 (Engels)`); their inhoudsindicatie is English. An
English inhoudsindicatie is kept as `summary_en`; the translation has `translation_of`, the ECLI
of the judgment it translates, and that judgment's Dutch `summary`, and the judgment its
`summary_en`. `summary` of a translation stays null while the judgment it translates is not
loaded.

`decision_kind` is what the decision is: `arrest`, `vonnis`, `beschikking`, `uitspraak`,
`beslissing` (the kantonrechter on a Wahv appeal, a wraking, the notariskamer), `conclusie` or
`prejudiciële beslissing` (`core.judgments.decision_kind`; the rule is in
[pipelines](pipelines.md#rechtspraak)); null when nothing tells, as for a decision of the Kroon.
A stub has the kind its kind of court gives (`data/curated/decision_kinds.json`).

`names` is what lawyers call the judgment (`Haviltex`, `Urgenda`, `Lindenbaum/Cohen`), from the
curated list of landmark cases (`data/curated/judgment_names.json`, `lawgraph curated`); empty for most judgments, null on a
stub without one. The open data carries no names: see [pipelines](pipelines.md#rechtspraak).

The judgments of one case are tied by `APPEAL_OF` (an appeal to the judgment it appeals),
`CONTINUES` (a judgment to an earlier one of the same court in the same case), `REFERRED_BY` (a
decision after referral to the Hoge Raad ruling that sent the case back), `ADVISES_ON` (a
conclusion to its judgment) and `ANSWERS` (a preliminary ruling to the decision that asked its
questions); `docs/pipelines.md`, Rechtspraak, says how each is found. Two judgments tied so
have no `REFERS_TO` between them, even when one names the other in its text.

`unresolved_appeal_targets` lists the decisions an appeal says in its text it appeals that are
not loaded (`court` and `case_number` as written, `date` ISO; `case_number` null when the text
gives none); null when there are none. `unresolved_citations` lists the articles a judgment
cites of laws that are not in the graph, the first 100 (`semantic rechtspraak`): `law` as written (or the law a
short name the judgment defines stands for: `Aanbestedingswet` for `Aw`), `article_number` as
written, `raw_match` and `qualifier` of the first citation, `leden`, `onderdelen`, `aanhef`,
`paragraph_ids`, `mention_count`; null when there are none.

Parallel cases a court decided on one day in (nearly) the same words form a series: each
judgment of it has `series_id`, the lowest ECLI in the series, and `series_size`; outside a
series both are null (`semantic rechtspraak-series`). A series has no edges.

A publication of a decision that another publication replaces (`dcterms:isReplacedBy`, kept as
`replaced_by`) is `SAME_AS` the one kept when that is loaded, and has its ECLI as `same_as`
(`semantic rechtspraak-duplicates`); the lists leave it out, and `/api/stats` and
`/api/stats/coverage` count it apart (`replaced`), so every count of judgments counts the decision
once. One whose replacement is not loaded has `replaced_by` and no `same_as`, and is counted. `inbound_citation_count` counts
the judgments that cite a judgment or a publication `SAME_AS` it, each once;
`outbound_citation_count` the judgments it cites.

`paragraphs` is the `<uitspraak>` (of a conclusion: the `<conclusie>`) in reading order, a list
of `{id, number, kind, text, continues}`. `kind` is `heading` (a section or a bridgehead),
`subheading` (a nested section, or the kop), `body`, `toc` or `signature`. `continues` is, of a
`body` paragraph without a number, the `id` of the numbered consideration it goes on with, up to
the next number or heading (absent otherwise). The first paragraph is the kop, a `subheading` of
its lines with a blank line between: court, case number, date and parties, however the court
sets them; a judgment may have none. How the kop, the headings, a table of contents and a
signature are told apart: [pipelines](pipelines.md#judgment-paragraphs).

A numbered unit of the XML (`<paragroup>`, however deeply nested) is one `body` paragraph with
its own text: the text of `5.3` does not hold `5.3.1`. `number` is the number as printed without
its closing dot (`5.3`), null when there is none, and is not part of `text`. `id` names the
paragraph in deep links and mentions and is unique in the judgment: `rov-5.3` for a numbered
`body` paragraph (a consideration, cited as "rov. 5.3"), `kop-5` for a numbered heading,
`p-3f2a9c1e` for a paragraph without a number (and a line of a table of contents, from its
number and text): the first 8 hex of the SHA-1 of its text, whitespace collapsed
(`core.judgments.text_id`), so it follows the text and not the position. An id that repeats one
before it gets `_<n>`, its occurrence (`rov-1_2`, or the same text twice).

`advocate_general` is, for a conclusion, who wrote it, as the lines before its parties name them
(`core.judgments.advocate_general`): a line of initials and a surname (`T. Hartlief`), or a name
behind "mr." (`mr. P.J. Wattel`, "Zaaknr: 18/04298 (Prejudicieel) mr. Wattel": `Wattel`), two
together as one ("F.F. Langemeijer en M.H. Wissink"); null when they name no one. The signature
at the end gives the office and, below it, the role they sign in: `advocate_general_role`
(`core.judgments.advocate_general_role`) is `advocaat-generaal` ("A-G", "AG",
"Advocaat-Generaal", "(a.-g.)"), `waarnemend advocaat-generaal` ("Wnd. A-G") or
`plaatsvervangend procureur-generaal` ("plv.") or `plaatsvervangend advocaat-generaal`
("plv. AG"); null when the signature writes none (an A-G signs so too) or one that is not
clear. The heading of the office at the top is
no role.

`parties` is what the kop names, in its order (`core/judgment_parties.py`), a list of `{name,
role, roles, role_stated, side, alias, representatives}`; empty when the kop names none:

| Field | Meaning |
|-------|---------|
| `name` | as the judgment writes it, anonymised where the source is (`[eiser]`, `MAATSCHAP GRONINGEN`), without its legal form ("de stichting"), place or role |
| `role` | `Verdachte`, `Betrokkene`, `Klager`, `Veroordeelde` (also a terbeschikkinggestelde), `Eiser`, `Gedaagde`, `Verzoeker`, `Verweerder`, `Appellant`, `Geïntimeerde`, `Belanghebbende`, `Opposant`, `Wederpartij`; `Partij` when none applies |
| `roles` | every role the judgment names for the party, in its order; `[role]` when it names none |
| `role_stated` | the judgment names the role: a role line ("EISERS in eerste aanleg,", which holds for every party above it since the one before), a role behind the name (", eiser", "(appellante)", "hierna: de verdachte"), the opener ("Uitspraak op het hoger beroep van:"), a list of designations ("verzoekster 1 als: [X]") or an anonymised name that is a role (`[verdachte]`, `[klager 1]`). Otherwise the role is derived from the area of law (the first `subjects`) and the side: Strafrecht `Verdachte`; Civiel recht `Eiser` (`Verzoeker` in a beschikking) against `Verweerder` (`Geïntimeerde` against a stated `Appellant`); Bestuursrecht `Appellant` against `Verweerder`; `Belanghebbende` on no side |
| `side` | `first` before "tegen" or "en", `second` after it (the verdachte of "in de strafzaak tegen" too), `other` for a belanghebbende that is not the first party. A party of the case an appeal was against ("tegen de uitspraak ... in het geding tussen:") that is not an appellant is on the `second` side; one named again, there or in a joined case, is one party |
| `alias` | what the judgment calls it: `EBN` for "hierna: EBN", distributed over "hierna respectievelijk: de Maatschap en NAM", or a short name in parentheses whose letters are in the name (`(Uwv)`) |
| `representatives` | `{name, role}`, `role` `advocaat` or `gemachtigde`: "advocaat: mr. X", "(gemachtigde: mr. Y)", for the parties named since the last one |

A `REFERS_TO` edge from a judgment to an article (`semantic rechtspraak`) is one per judgment and
article. Its `confidence` is that of the strongest mention, `meta.mention_count` the number of
mentions, `meta.reason` the kind of target, and `meta.mentions` the first 100 mentions in
reading order:

| Field | Meaning |
|-------|---------|
| `paragraph_id`, `paragraph_number` | the paragraph that cites the article (`number` is absent when it has none) |
| `start`, `end`, `raw_match` | the citation as written: `text[start:end]` of that paragraph |
| `qualifier` | what the citation says of the article's parts, as written: `derde lid` |
| `leden`, `onderdelen`, `aanhef` | what the qualifier names, as in the part ids of an article (`core/qualifiers.py`) |
| `snippet`, `confidence` | the text around the citation; 0.95 for a law named by its code or its title, less for a law that is found by "die wet" |

A Tweede Kamer document's edge to an article has `meta.raw_match`, `snippet`, `reason`, `qualifier`,
`leden`, `onderdelen` and `aanhef` of the first citation of that article.

## Parliament

A dossier holds cases, and a case holds documents. The Tweede Kamer's records are the source;
the Eerste Kamer adds its own votes, agendas, bills, factions and committees, each marked
`chamber` `EK` (label `EK`).

### Dossier (`dossiers`)

| Prop | Meaning |
|------|---------|
| `number`, `suffix`, `label` | `37020`, `XV`, `37020-XV`; the key is made from the label |
| `order` | a text that sorts dossiers as the Kamer does: by number, then no suffix, numeric suffixes, budget chapters, the rest (`core/dossier_numbers.dossier_order`) |
| `title`, `title_source` | its title and where it comes from |
| `kind` | what the dossier is: the `Zaak.Soort` of its own zaak as the Kamer writes it (`Wetgeving`, `Initiatiefwetgeving`, `Begroting`, `Verdrag`, `Initiatiefnota`, `PKB/Structuurvisie`; `core/dossier_stages.CARRYING_KINDS`); null without such a zaak. Never read from its papers |
| `kind_basis` | `case` when its zaak gives the kind, else null |
| `case_kinds` | the `Zaak.Soort` of its own cases |
| `same_number_count` | the other dossiers with the same number (`normalize tk-dossiers`) |
| `opened_on`, `opened_on_basis` | the date of nr. 1 of its own numbering (`first_paper`), else of its Koninklijke boodschap (`royal_message`), else of its first document or activity (`earliest_record`) |
| `submitted_on_tk` | the `Zaak.GestartOp` of its own zaak of a bill (`Wetgeving`, `Initiatiefwetgeving`, `Begroting`): the day the Kamer dates its submission |
| `last_activity` | the day of its newest paper, activity that took place or decision; refreshed by every `normalize tk-dossiers` that touches it |
| `phases`, `current_phase` | of a `Wetgeving`, `Initiatiefwetgeving` or `Begroting`: every phase of the curated list `phases` (`data/curated/phases.json`) in its order, `{name, done, date}`. A phase is done when a paper, an activity that took place or a decision on the dossier's own zaak has a value the list names for it; `date` is the first such date. `current_phase` is the furthest done phase |
| `closed`, `outcome`, `closed_on` | `semantic tk-dossier-outcomes`: `aangenomen` when its law was published or the Eerste Kamer adopted it, `verworpen` when a chamber voted the bill down. An open dossier has `closed: false` and no outcome (see Known limits for a withdrawal) |
| `tk_decision` | the last decision of the Tweede Kamer on its bill: `kind` (its `BesluitSoort`), `text`, `date` |
| `ek_outcome` | its outcome in the Eerste Kamer: `outcome` (`Aangenomen`, `Verworpen`), `date`, `method`, `source_url`, `retrieved_on` |
| `ek_rejected` | the Eerste Kamer's list of rejected bills names it: `date`, `source_url`, `retrieved_on` (`normalize eerstekamer-votes`) |
| `ek_bill` | the page of its bill on eerstekamer.nl (`normalize eerstekamer-bills`): `url`, `read_on`, `status`, `submitted_on`, and `progress` with `phase`, `house`, `state` and `papers`, as the page gives them |
| `ministry`, `initiative`, `cabinet` | who brought it in (`semantic tk-government`): the ministry of the bewindspersoon who first signed its earliest signed document, or `initiative: true` when a Kamerlid did; the cabinet in office that day |
| `first_signed` | that first signature: `date`, `member`, `capacity`, `function` and the `paper` (its id); null when no paper is signed so |

### Case (`cases`)

Every Zaak of the Tweede Kamer, whatever its kind.

| Prop | Meaning |
|------|---------|
| `title` | `Zaak.Titel`; of a motie, amendement, letter or report its `Onderwerp` (its `Titel` is its dossier's) |
| `citation_title`, `number` | as the Kamer writes them |
| `kind` | `Zaak.Soort` (`Wetgeving`, `Motie`, `Brief regering`, …) |
| `dossier_numbers`, `started_on` | its dossiers; `Zaak.GestartOp` |
| `related_cases` | `Zaak.GerelateerdNaar`: `id`, `kind` and `dossier_numbers` of each case the Kamer relates it to (read by `semantic tk-dossier-relations`) |

### Document (`documents`)

A paper of the Tweede Kamer, a Staatsblad or Staatscourant publication, or a paper of the Eerste
Kamer; the chamber is in `labels` (`TK`; `EersteKamer` and `EK`). A `kind` that contains
`toelichting` makes a document explanatory.

| Prop | Meaning |
|------|---------|
| `kind`, `date`, `subject` | `Document.Soort`, its date and subject |
| `title` | `Titel`; of a motie, amendement, letter or report its own `Onderwerp`, else that of its zaak |
| `dossier_title` | of those: its `Titel`, which is the title of the dossier |
| `number` | its own number: a Kamerstuk number, or that of a Staatsblad or Staatscourant |
| `document_number` | `DocumentNummer` (`2026D44984`), by which tweedekamer.nl finds it |
| `sequence`, `session_year` | its number within `dossier_number`; its vergaderjaar |
| `dossier_number`, `dossier_suffix` | `Document.Kamerstukdossier`: the one dossier it is a Kamerstuk of; null for a paper that is none (a nader rapport sent with a bill) |
| `dossier_numbers` | the dossiers of its cases and its own, as labels |
| `case_ids`, `case_kinds` | its cases and their `Zaak.Soort` |
| `actors` | every signature (below) |
| `activity_ids`, `attachment_ids`, `attached_to_ids` | `Document.Activiteit`, `BijlageDocument`, `BronDocument`: the activities it is the record of (a stenogram: its debate), its attachments, the letters it is an attachment of (TK ids); the edges MADE_IN and ACCOMPANIES follow them |
| `text` and its structure | `normalize tk-content` (below) |
| `raw` | the record of the Tweede Kamer as it came |
| `url` | of a paper of the Eerste Kamer: its page on officielebekendmakingen.nl, as the source gives it |
| `identifier`, `year`, `bwb_id` | of a Staatsblad or Staatscourant publication |

### Activity (`activities`)

| Prop | Meaning |
|------|---------|
| `number` | `Activiteit.Nummer`, by which tweedekamer.nl finds it |
| `date`, `agenda_title`, `kind` | its date, `Onderwerp` and kind (a debate, a hearing) |
| `status` | `Gepland`, `Uitgevoerd`, `Geannuleerd`, `Verplaatst`, `Vervallen`, as the Kamer writes it |
| `replaced_by` | `Activiteit.VervangenDoor`: the numbers of the activities that replace it |
| `committee_id` | null for a plenary activity |
| `case_ids`, `dossier_numbers`, `case_kinds_by_dossier` | what it is about |
| Eerste Kamer | `normalize eerstekamer-agenda`, key `ek_<id>` of a plenary block or `ek_<yyyymmdd>_<committees>` of a committee meeting: `date`, `time`, `kind` (`plenaire vergadering`, or the kind of a meeting as its agenda gives it), `agenda_title` (the block's title, or the committees), `decision_points` of a meeting (`id`, `number`, `reference`, `dossiers`, `subject`, `decision` as the committee words it), `source_url`, `retrieved_on`. No `status`: the Eerste Kamer gives none |

### Decision (`decisions`)

One node per `Besluit` of the Tweede Kamer, key `decision_<Besluit_Id>`.

| Prop | Meaning |
|------|---------|
| `decision_id`, `agenda_item_id` | the `Besluit` and its agendapunt |
| `date`, `subject`, `agenda_item_subject` | the day, and what the decision and its agendapunt are about |
| `decision_kind`, `decision_text` | `BesluitSoort` (`Stemmen - aangenomen`, `Stemmen - verworpen`, `Stemmen - zonder stemming aannemen`, `Stemmen - uitstellen`, …) and its text |
| `decision_order`, `meeting_kind` | its order on the agendapunt (`AgendapuntZaakBesluitVolgorde`); the kind of meeting (`Vergadering_Soort`) |
| `case_ids`, `dossier_numbers` | what it is about |
| `primary_case_id`, `primary_case_kind` | the zaak it decided (`Wetgeving` on the vote on a bill itself) |
| `kind` | what was decided on: the `Zaak.Soort` of the primary case; without one the Soort of the cases on its agendapunt when they are all of one; else null. Never read from the subject |
| `passed` | from the `BesluitSoort`, else the tally; null for a decision that is no vote |
| `vote_kind`, `tally`, `voters` | `member` or `faction`; seats per choice (members per choice on a roll-call); how many cast each choice. A decision on a bill without votes (a hamerstuk) comes from a `tk-besluit` record and has no `tally` and `vote_kind` null |
| Eerste Kamer | `normalize eerstekamer-votes`, key `ek_<date>_<label>_<n>`: `result` and `method` as eerstekamer.nl writes them, `factions_for`, `factions_against`, `factions_noted`, `bill_url`, `source_url`, `retrieved_on`; `bill_decision` and `kind` from `semantic tk-dossier-outcomes` (the vote that decided the bill, with the kind of its dossier) |

### Commitment (`commitments`)

| Prop | Meaning |
|------|---------|
| `number` | `TZ202603-130`, how the Kamer cites it |
| `text`, `made_on`, `activity_number` | the commitment, the day it was made and its activity |
| `minister_name`, `minister_role`, `ministry_name` | as the Kamer writes them (`Toezegging.Ministerie`) |
| `expected_resolution` | `0001-01-01` when the Kamer names none |
| `status` | `Toezegging.Status` as the Kamer gives it: `Openstaand`, `Afgedaan`, `Deels Afgedaan`, `Nagekomen`, `Niet nagekomen`, `Vervallen` |
| `letter_ids` | `Toezegging.KamerbriefNakoming`: the letters that fulfil it (TK ids); each stored one `ANSWERS` it |
| `member_key`, `post`, `ministry`, `cabinet` | `semantic tk-government`: who made it, in which post and ministry, and the cabinet in office that day |

### Member (`members`)

Every `Persoon` of the Tweede Kamer, members and ministers. A minister who never sat in
parliament has no name or date of birth there, and a few records are empty: such a member takes
the name its roll-call votes or signatures give for its `Persoon_Id` ("Nobel, J.N.J." becomes
`J.N.J. Nobel`); an early member whom the Kamer knows only by initials and surname is named by
them (`W.B. Buma`). A bewindspersoon without a `Persoon` is a member of their own (label
`Rijksoverheid`, key `rijksoverheid_<initials>_<surname>`).

| Prop | Meaning |
|------|---------|
| `name`, `full_name`, `initials` | the name they go by (`Roepnaam` and surname), `Voornamen` and surname, `Initialen` |
| `family_name`, `name_prefix` | `Achternaam` without the `Tussenvoegsel`, and the tussenvoegsel |
| `number`, `birth_date` | `Persoon.Nummer`; the date of birth |
| `slug` | the name as the API gives it, lower-case ASCII with hyphens (`core/member_slugs.py`). Given once by every pipeline that writes members and never changed; a later namesake gets the year they were born, else `number`, else a number of its own. `lawgraph check` fails on a slug two members share |
| `party`, `faction_memberships` | the party, and every faction membership with its dates |
| `government_name`, `known_as` | from Rijksoverheid: `S.Th.M. Hermans`, and `Sophie Hermans` (the first name the page gives; null when none) |
| `government_functions` | every post in a cabinet since 1945, oldest first (below) |
| `ek` | a member of the Eerste Kamer (`normalize eerstekamer-composition`): `name` as its page writes it, `path` and `url` of that page, `faction` (key) and `abbreviation`, `seniority_days` (`Anciënniteit`), `residence`, `observed_from`, `observed_until`, `retrieved_on`. It is the member of the Tweede Kamer born that day whose surname ends its name, when exactly one is; else a member of its own (`ek_<slug>`, label `EK`, with `name` and `birth_date` from the page) |

A post in `government_functions` (`normalize rijksoverheid`, [pipelines](pipelines.md#rijksoverheid)):

| Field | Meaning |
|-------|---------|
| `cabinet_key`, `cabinet` | the cabinet node, and its name |
| `function`, `also_named` | the post as the source writes it, and the other names it has |
| `post`, `seat`, `portfolio` | the normalised post, the seat (`ienw/minister`, `-/staatssecretaris/rechtsbescherming`, `viceminister-president`) and the portfolio |
| `ministry` | the key of its ministry (`core/post_ministries.py`), with `ministry_source` (`page`, `tk_signatures`, `tk_commitments`, `staatscourant`); when null, `ministry_missing` (`no_source`, `ambiguous`) |
| `from_date`, `to_date` | the period held (`to_date` null while held); `from_date_source` and `to_date_source` the dates the page gave, `corrected` the dates the rules of a seat set |
| `acting` | a stand-in, with `acting_reason` (`source`, `held_other_seat`), `acting_basis` (the page's words) and `acting_other_seat` (`seat`, `function`) |
| `party` | `short` and `faction` |
| `overlaps_with`, `absent` | members holding the seat at the same time; periods of "tijdelijk afwezig" |
| `name`, `source` | the holder as the page writes them; `name`, `url` and `read_on` of the page |

### Faction (`factions`)

| Prop | Meaning |
|------|---------|
| `name`, `abbreviation`, `aliases` | the key is the abbreviation, else the name (`vvd`, `d66`) |
| `seats`, `seats_changed_on` | `AantalZetels` (0 once the faction has ended); the day one of its seats last changed (`FractieZetel.GewijzigdOp`) |
| `active`, `active_from`, `active_until` | the first and last day its seats were held, where the seats date it (from 30 November 2006); else the Fractie record's |
| `external_id`, `external_ids` | the current Fractie record, and every Fractie record of the faction: a faction that returns gets a new record (50PLUS 2012-2021 and from 2025), and votes and seats name either |
| Eerste Kamer | key `ek_<slug>`: `chamber` `EK`, `name` (the heading of its page, `D66-fractie`), `abbreviation`, `seats` (as `/fracties` lists them), `active`, `board` (`function`, `name`, `member`, `since`), `url`, `retrieved_on`, `observed_from`, `observed_until`, `data_since` |

### Committee (`committees`)

Only a Commissie with a name; the plenary is no committee.

| Prop | Meaning |
|------|---------|
| `name`, `abbreviation`, `slug` | `slug` is unique (`GET /api/committees`) |
| `kind` | by its name, else `Commissie.Inhoudsopgave` |
| `started_on`, `ended_on` | `DatumActief`, `DatumInactief` |
| `active_dossier_count` | the open dossiers it leads, none once dissolved (`semantic graph-list-stats`) |
| Eerste Kamer | key `ek_<slug>`, `slug` `ek-<slug>`: `chamber` `EK`, `name`, `abbreviation`, `title`, `url`, `retrieved_on`, `observed_from`, `observed_until`, `data_since` |

### Cabinet (`cabinets`)

A Dutch cabinet since 1945, from its Rijksoverheid page; key from its name (`rutte_asscher`,
`den_uyl`).

| Prop | Meaning |
|------|---------|
| `name` | `kabinet-Rutte-Asscher` |
| `from_date`, `to_date` | the beëdiging; null while in office |
| `previous`, `prime_minister` | the cabinet before it; the member key of its prime minister |
| `parties`, `factions` | `short` and `faction` of the bewindspersonen sworn in on the first day; their faction keys |
| `phases` | `kind` (`formatie`, `in_functie`, `demissionair`, `dubbel_demissionair`, `missionair`, or null), `from_date`, `to_date`, `label` in the source's words, `source` |
| `demissionary_from` | the day it went demissionary |
| `origin` | `name`, `url` and `read_on` of the page |

`MEMBER_OF` into a faction or committee of the Eerste Kamer has `meta.chamber` `EK`,
`observed_from`, `observed_until`, and `seniority_days` (faction) or `role` (committee).

No link to tweedekamer.nl is stored. The site finds a document by its `document_number` and an
activity by its `number`, never by the GUID of the record (`external_id`), so the API derives
`tk_url` from those when it answers (`core/tk_links.py`): a template that turns out wrong is
fixed by a release, not by a migration. The Eerste Kamer papers keep the `url` of their page on
officielebekendmakingen.nl as the source gives it.

Dossiers of different numbers are tied by four edges, written by `semantic
tk-dossier-relations` (the rules: [pipelines](pipelines.md#semantic-tk-dossier-relations)):
`REVISES` (a supplementary budget or slotwet → the budget of its chapter and year), `ACCOMPANIES`
(a budget change → the Voorjaarsnota, Najaarsnota or Miljoenennota it is submitted with),
`RELATED_TO` (the Kamer relates a case of the one to a case of the other) and `SECOND_READING_OF`
(a change in the Grondwet in its second reading → its first reading, whose memorandum explains
it). The dossiers of one
number are found by the number itself (`GET /api/dossiers?number=`), not by an edge.

### Text and sections of a Kamerstuk

`normalize tk-content` reads the Kamerstuk XML that `retrieve tk-content` stored and writes,
on the Document of the paper (`meta.document` of the raw record):

| Prop | Meaning |
|------|---------|
| `text` | one line per heading, paragraph, list item or table row (cells tab-separated), whitespace collapsed; footnotes, header and signature are not in it. Cut at a whole line at 2,000,000 characters (`MAX_TEXT_CHARS`; the longest paper seen has 1.1 million) |
| `text_truncated` | `true` when it was cut |
| `text_source` | `kst-xml` |
| `xml_dialect` | `kamerwrk` (1995-2009) or `officiele-publicatie` (2010 on) |
| `structure_quality` | `explicit`: an artikelsgewijs opener and article headings after it; `implicit`: article headings, no opener; `none`: no article headings |
| `budget` | a budget or annual report (a dossier chapter such as `XV`, or a title that says so): its numbered articles are policy articles, not law articles, so a consumer that links articles skips it |
| `footnotes` | `[{number, text}]` in document order |
| `sections` | the headings of the paper, in document order, as below |

The XML has no element for an article: the artikelsgewijs part of a memorandum is a run of
headings with the paragraphs after them. Every heading is a section, so `sections` covers the
whole paper; a section spans its heading, its body and everything nested under it:
`text[char_start:char_end]`. A child lies inside its parent.

| Field | Meaning |
|-------|---------|
| `id` | `s-<ordinal>` in document order; the same XML always gives the same ids |
| `heading` | the heading as printed (`ARTIKEL II (Huisvestingswet 2014)`) |
| `level` | 1 for a section without parent, else the level of the parent plus 1 |
| `parent` | id of the enclosing section, or `null` |
| `kind` | `algemeen` (the general part: every heading before the opener); `artikelsgewijs` (the heading that opens the article-by-article part: "Artikelsgewijs", "Artikelsgewijze toelichting", "Artikelen"); `article` ("Artikel 3", "Artikelen 3 en 4", "Artikel I, onderdeel B (artikel 1a)"); `onderdeel` ("Onderdeel B", "Ad a.", "A, B en D"); `lid` ("Eerste lid", "Ad 1"); `chapter` ("Hoofdstuk 2", "Afdeling 3"); `other`. `onderdeel` and `lid` only inside an article; an article heading is one wherever it stands |
| `number` | the number as printed in the heading (`3`, `II`, `3:159n`, `1.6.20`, `B`); of the first article for a heading with several; `lid` numbers are digits (`Eerste lid` is `1`); `null` when the heading has none |
| `number_scheme` | `arabic`, `roman`, `book_article` (`3:159n`, `1.6.20`), `letter` (`B`), or `null` |
| `article_refs` | `[{number, of}]`: every article number the heading names (`Artikelen 3 en 4` gives two; `1 tot en met 3` gives 1, 2, 3), empty for other kinds. `of`: `self` (an article of the bill the memorandum accompanies), `named_law` (of the law `law` names: `Artikel 1a van de Woningwet`), `unknown` (of a law that is implied and not named: the `(artikel 1a)` of `Artikel I, onderdeel B (artikel 1a)`, or the parenthesis of `Onderdeel A (artikel 1)`) |
| `law` | another law the heading names, in parentheses or after `van de` (`Huisvestingswet 2014`, `Boek 7 van het Burgerlijk Wetboek`), else `null`; on an `article` whose number is the bill's own it is the law that bill article changes |
| `char_start`, `char_end` | offsets into `text` |

A paper that cannot be read gives no text and the record is skipped; a paper whose structure
cannot be read gives its text, no sections and `structure_quality` `none`.

Votes: TK returns one row per voter per `Besluit`. A roll-call (`Hoofdelijk`) names every
member, so its `VOTED` edges start at the member; any other vote is cast per faction and the
edge starts at the faction. The decision carries `vote_kind` (`member` or `faction`), `tally`
(seats per choice, members per choice on a roll-call), `voters` (how many cast each choice)
and `passed`; each edge carries `meta.choice`, `meta.seats` (the seats of the faction; 1 for a member on a roll-call, whose row carries the size of the faction) and `meta.record_ids` (the Stemming it is made of). The API derives a member's
non-roll-call votes from the faction they belonged to at the time, using
`members.props.faction_memberships`.

Authorship is stored on the document (`props.actors` with `person_id`, `faction_id`, `name`,
`faction`, `role`, `function`, `capacity`) and as `AUTHORED` edges from the signatory, with
`meta.role`, `meta.function` and `meta.capacity`. Only people get an edge; which faction signed
follows from the signatory's faction membership.

A person's role changes over time: R.A.A. Jetten signed as Tweede Kamerlid until 2025 and as
minister-president in 2026, S. van Haersma Buma, once a Kamerlid, signs the advices of the Raad
van State as its vice-president. So each signature keeps what it was signed as:

- `function` is `DocumentActor.Functie` as the source writes it (`Tweede Kamerlid`,
  `minister-president`, `staatssecretaris van Financiën`, `griffier`, `vicepresident van de Raad
  van State`, `voorzitter van de vaste commissie voor …`);
- `capacity` is derived from it (`tk_records.signing_capacity`), the first that holds:
  `bewindspersoon` when the function begins with `minister`, `minister-president`,
  `viceminister-president` or `staatssecretaris` (not `gevolmachtigde minister van Aruba`, who
  speaks for Aruba); `kamerlid` when the signature is for a faction (`Fractie_Id` or
  `ActorFractie`: a member, also as the chair of a committee, a formateur or verkenner); `overig`
  otherwise (the griffier, the Raad van State, the Algemene Rekenkamer, the Nationale
  ombudsman). No minister or staatssecretaris signs for a faction in the source.

`MEMBER_OF` edges run from a member to a committee (`meta` = the seat that represents the membership: `from_date`, `to_date`, `role` (`Functie` of `CommissieZetelVastPersoon` or `CommissieZetelVervangerPersoon` as the Kamer writes it: `Lid`, `Voorzitter`, `OnderVz`, `Plv. lid`), `substitute` for a substitute's seat, and `periods`, every seat oldest first, when there is more than one or it has a role; an open seat represents before a closed one, a member's before a substitute's) and to a
faction (`meta.from_date`, `meta.to_date`, `meta.role`, `meta.record_ids`: the
FractieZetelPersoon records it is made of). Edge keys are one per pair, so a
member who leaves and rejoins keeps one edge with the latest period, whatever order the records
are read in: the latest `from_date`, of two that start the same day the one without an end,
then the later `to_date`; the full timeline is in `members.props.faction_memberships`. `to_date` is the last day held (`TotEnMet`), so periods
that follow each other touch without overlap. Where the Kamer's dates do not hold together its
later dates are read (`core/seat_periods.py`): an end before the start ends the day before the
person's next seat (without one the seat is left out), and a fractievoorzitter still chairing
when the next one starts chairs until the day before and holds the rest of that seat as `Lid`.

## raw_sources

`{_key, source, kind, external_id, fetched_at, payload_json, payload_ref, payload_chars, meta}`.
JSON sources keep their payload in `payload_json`, in the database, where queries filter on it.
The XML or HTML of the other sources (most of what LawGraph stores; nothing queries inside it)
is an object in the payload store (`db/payloads.py`, `LAWGRAPH_PAYLOAD_STORE`: a directory or an
S3 bucket), gzip-compressed, named `<database>/<source>/<kind>/<_key>.gz`; the document keeps
that name in `payload_ref` and the length of the text in `payload_chars`. The object is written
before the document. `store.with_payloads(records)` reads the objects of a stream of records,
side by side, and puts each text back in `payload_text`; a missing object is logged and the
record is skipped like one without a payload.

| Source | Kinds |
|--------|-------|
| `tk` | `tk-zaak`, `tk-document`, `tk-dossier`, `tk-activiteit`, `tk-stemming`, `tk-besluit`, `tk-toezegging`, `tk-commissie`, `tk-persoon`, `tk-fractie`, `tk-fractie-zetel-persoon`, `tk-kamerstuk-xml` (the XML of a paper, external id `kst-<dossier>-<n>`, `meta.document` the key of its Document) |
| `rechtspraak` | `rs-content`, `rs-instanties-xml` (the Instanties value list) |
| `eurlex` | `eu-celex-html`, `eu-nim-json` (the Dutch implementing measures of an act) |
| `bwb` | `bwb-toestand-xml` (current), `bwb-toestand-xml-all` (every toestand, external id `<bwb_id>@<start_date>`), `bwb-wti-algemene-informatie-xml` (the first element of the WTI file: official abbreviations, citation titles, legal areas) |
| `staatsblad` | `stb-amvb-xml` |
| `staatscourant` | `stcrt-regeling-xml`, `stcrt-post-creators-json` (per cabinet post, the ministries that issued the publications naming it) |
| `eerstekamer` | `ek-kamerstuk-json`, `ek-votes-day-html`, `ek-rejected-html`, `ek-composition-html`, `ek-bill-html`, `ek-plenary-html`, `ek-committee-day-html` |
| `echr` | `echr-judgment-json` (one per HUDOC item: a judgment in one language), `echr-judgment-docx-xml` (the `word/document.xml` of the DOCX of the item whose text a judgment gets, external id its item id, `meta.ecli` and `meta.language`) |
| `verdragenbank` | `verdrag-json` (the SRU record), `verdrag-xml` (the item XML: parties, Tractatenbladen, dossiers, related treaties; `meta.item_url` and `meta.modified`) |
| `rijksoverheid` | `rijksoverheid-cabinet-html` (the page of one cabinet since 1945, external id its slug, `meta.url` and `meta.read_on`) |
| `tooi` | `tooi-ministries-jsonld` (the ministries list, external id `rwc_ministeries_compleet`), `tooi-thesaurus-jsonld` (a thesaurus of the BWB, external id `scw_bwb_rechtsgebieden` or `scw_bwb_themas`); each `meta.url` and `meta.read_on` |

A document the source answered HTTP 404 for is remembered as a record without payload of
kind `<kind>-missing` (`eu-celex-html-missing`, `rs-content-missing`, ...), which no other phase
reads. A retrieve does not ask for it again for 30 days, or for 3 when the source itself listed
it (an index, an SRU listing: its file is probably on its way); `pipelines/retrieve/base.py`.

## Tables, indexes and search

Defined in `db/schema.py` and created when the store starts (`ensure_schema`). The store refuses
a database whose tables differ from the schema (`SchemaOutdated`), and one that does not sort
strings by the ICU collation `und-u-kf-upper` of `create_database_sql` (`CollationMismatch`): the
queries compare and sort strings by it. Either is built again.

### Tables

Every node collection is a table of the same shape: `id` (`collection/key`),
`key`, `type`, `labels` and `props` (`json`, so the API serves the keys in their stored
order). `edges` holds `key`, `from_id`, `to_id` and the rest of the edge as `doc`;
`raw_sources` and `pipeline_state` hold their documents as `doc`, `raw_sources` with the
generated columns `source`, `kind`, `external_id` and `fetched_at` and the indexes
`(source, kind, key)` and `(source, fetched_at)`. The view `nodes` unions the node tables for a
lookup by id.

`lg_data_version` holds a counter per table of the graph. A statement trigger on each
(`<table>_version_insert`, `_update`, `_delete`) raises it with every statement that changes
the table; a retrieve changes none of them. The API's `ETag` is made from these counters
(`GraphStore.data_version`). An answer the API keeps names the tables it reads
(`version_cache.cached(tables=...)`) and is kept while their counters stand still, an hour at
most; one that names none is kept until any counter moves.

### Derived columns

What a query filters, sorts or counts on is a column of its own: a
string, number, boolean or list of strings from one prop, or a prop as stored (`pj_<prop>`)
where the props are large (a judgment's text). A trigger of the table (`<table>_derive`) fills
them from `props` when a row is written, reading the props once. Of an edge, `relation`,
`source`, `status`, `confidence`, `semantic_type`, `meta.record_ids` and `created_at`, and the
collections of both ends, are generated columns of `doc`.

### Indexes

B-tree indexes on those columns, as `INDEXES` in `db/schema.py` lists them per
table: the identifiers (unique where they are: `bwb_id`, `celex`, `ecli`), the fields the
lists filter and sort on, and for `/api/judgments` one index per filter that holds the tier,
the kind of court, the source, the date, `stub` and `same_as`, so its facets count from the
index alone, `(tier, published_on)` for the judgments of the feed, a page per tier, and a GIN index on `lg_subject_areas(subjects)` (each subject up to its first `;`, each main area once) for `subject_area`. A GIN index on each list column (`labels`, `subjects`, `case_number_keys`,
`dossier_numbers`, `cabinet_keys` of members). Ordered indexes for the instruments list (partial: without the
publications), the documents newest first, and the member lists in name order. `edges`:
`(from_id, relation, to_collection)`, `(to_id, relation, from_collection)`, the same two
with `key` after them and the other end and collection included (`edges_from_cover`,
`edges_to_cover`: a level of `/api/paths` reads a node's edges from the index alone, and a
page of a node's neighbours reads its keys from it in key order, stopping after its limit,
and only those edges whole), `relation`,
`(status, relation)`, `confidence`, `(created_at, to_id)`, a GIN index on `record_ids`, and
`semantic_type` and `(from_id, semantic_type)` where `semantic_type` is set.

### Search

`/api/search` reads search columns of `articles`, `instruments`, `judgments`,
`dossiers`, `documents` and `committees`, a few per field, each for one way of matching
(`s_<field>_<suffix>`):

| Suffix | Holds | Finds |
|---|---|---|
| `t` | the words, folded and stemmed as the Dutch `text_nl` (`lg_tokens`: `uitspraken` → `uitspraak`; English texts such as ECHR summaries are stemmed as Dutch too) | a word |
| `v` | the values whole | an identifier as written |
| `n` | the values lower-cased, without accents | an identifier in any case |
| `g` | the values folded, joined | a part of a word (`vordering` finds `Strafvordering`), through a trigram index |
| `p` | every value after a separator | a value by its beginning |

GIN indexes back the `t` and `n` columns, trigram indexes the `g` and `p` columns. A hit is
ranked by BM25 over the words it matches (`queries/_bm25.py`, with the weights of
`search_tsv`). The columns are written with the row, so a fresh
insert is found at once. `members` and `factions` are searched by their names
(`search_names`, a trigram index); `cabinets` by their name, `commitments` by their text and
number, and `decisions` by their subject and kind, each through a trigram index on those
words lower-cased (`<table>_search_words`).
`articles` are searched by their `display_name`, `heading`, the `title` of every division in
the `breadcrumb` (`breadcrumb.title`), `text`, `article_number` and `bwb_id`; `instruments`
by their titles, `short_title`, `aliases` and `bwb_id`; `judgments` by each of their `names`
as words, whole and in parts, besides their `display_name`, `summary`, `ecli` and `appno`.

An instrument's `aliases` are every name it is cited by: the official WTI abbreviations
(`Sr`, `WvS`, `WvSr`) and, for a book of a code in `core/code_families.CODE_FAMILIES` (from the WTI), `Boek 6 BW`, `6 BW`,
`BW 6`, `BW6`, `BW Boek 6` and `BW`. Unlike `short_title` an alias may be shared: `BW` is one
of every book. Written by `normalize bwb`.

## Known limits

What the graph deliberately does not hold, because no official source gives it:

- Cabinets before 1945: Rijksoverheid describes the cabinets since 1945 only, and no other
  official source gives the posts or phases of the earlier ones.
- Who followed whom in an unnamed seat: where the Rijksoverheid page names no portfolio (two
  staatssecretarissen of one ministry, two ministers without portfolio), it does not say who
  succeeded whom: the holders are put in lanes by date (`fin/staatssecretaris`,
  `fin/staatssecretaris#2`), and a successor in such a seat is the next holder in its lane.
- Bewindspersonen without a TK person: a post holder whom no Tweede Kamer `Persoon`
  matches is a member of their own (label `Rijksoverheid`, key `rijksoverheid_<initials>_<surname>`),
  with the name Rijksoverheid gives and no parliamentary record; `lawgraph verify cabinets`
  counts them per cabinet (`own`).
- Posts without a ministry: a post whose ministry no source settles keeps `ministry` null,
  with `ministry_missing` `no_source` or `ambiguous` (see
  [pipelines](pipelines.md#rijksoverheid)); `lawgraph verify cabinets` counts and lists them.
- Versions of EU articles: an EU act is loaded as CELLAR serves its CELEX number, the text as
  adopted. Consolidated versions are not fetched, so an EU article has no `article_versions`
  and does not show the changes of a later act.
- The Eerste Kamer before the first snapshot: eerstekamer.nl shows who sits in its factions
  and committees today, and gives the start and end of a membership only in sentences (and the
  seats since 1946 only as a PDF). The graph keeps what each snapshot shows: a membership, a
  faction or a committee runs from the first snapshot that shows it (`observed_from`) to the
  first that no longer does (`observed_until`). Nothing before the first snapshot is known,
  and `seniority_days` (`Anciënniteit`) is no start date.
- Withdrawal of a bill: the Tweede Kamer records no withdrawal as data of the bill or its
  case (its zaak keeps `Status` `Vrijgegeven`), so there is no outcome `ingetrokken`: a
  withdrawn bill stays open (see [pipelines](pipelines.md), `tk-dossier-outcomes`).

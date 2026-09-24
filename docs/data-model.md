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
  `member`, `faction`, `committee`, `topic`). Every type has its own collection and every
  collection holds one type (`core.models.COLLECTION_OF_TYPE`), so the collection in an id
  says the type.
- `labels` tag the origin (`BWB`, `EU`, `TK`, `Rechtspraak`, `ECHR`, `EersteKamer`, ...). Upserts
  union labels.
- `props` are validated against a strict Pydantic schema per collection (`core/props.py`);
  unknown fields are rejected. Upserts merge props (shallow), so several pipelines can add
  fields to one node.
- `stub: true` marks a placeholder created because something referred to it before its own
  source was ingested.

Other collections: `raw_sources` (the records as fetched, their XML and HTML in the payload
store), `topics` (schema only; nothing writes it), `pipeline_state` (one document per phase:
when its last complete `<phase> all` began, for `--since last`).

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
| Committee | `committees` |

| Relation | From | To | Meaning |
|----------|------|----|---------|
| `PART_OF` | Article / Annex / Document / Case | Instrument / Case / Dossier | Containment. Article/Annex → Instrument; Document → Case or Dossier; Case → Dossier. |
| `VERSION_OF` | InstrumentVersion / ArticleVersion | Instrument / Article | A dated version of an instrument or article. An article keeps one identity across versions (BWB `stam-id`); each version has valid_from / valid_until. |
| `AMENDS` | Instrument / Document | Instrument / Article | An instrument changes existing text (effective date and version in `meta`). A bill (Document) proposing the change carries status `voorgesteld`. |
| `INTRODUCES` | Instrument / Document | Instrument / Article | An instrument adds a new article or instrument; a bill proposing it is `voorgesteld`. |
| `REPEALS` | Instrument / Document | Instrument / Article | An instrument withdraws an article or instrument; a bill proposing it is `voorgesteld`. |
| `BASED_ON` | Instrument | Article | The legal basis (delegation basis) an instrument is issued under: 'Gelet op artikel …' in the preamble. |
| `IMPLEMENTS` | Instrument | Instrument | A national instrument whose text names the CELEX number of an EU act; not a transposition claim, and not per article. |
| `LEGISLATED_IN` | Instrument | Dossier | The parliamentary dossier in which an instrument was legislated (BWB `dossierref`). |
| `REFERS_TO` | Article / Document / Judgment | Article / Instrument / Judgment | A text refers to an article, instrument or judgment. The source node says who refers; article → article edges also carry a `semantic_type`. |
| `EXPLAINS` | Document | ArticleVersion / Article / Instrument | A document (MvT, NvT) explains the article version or instrument it introduced or changed. Written per dossier: every MvT and NvT of a dossier explains everything its law changed; an MvT edge carries `meta.section_anchor` when one of its sections is about that article. |
| `APPEAL_OF` | Judgment | Judgment | An appeal or cassation judgment → the judgment it appeals. |
| `ADVISES_ON` | Judgment | Judgment | The conclusion of an advocate-general (Parket bij de Hoge Raad, or of the court itself) → the judgment in its case: the formal relation of either (`meta.basis` `formal_relation`), else a case number the two share (`case_number`). |
| `ANSWERS` | Judgment | Judgment | A preliminary ruling (prejudiciële beslissing) → the decision that asked its questions: the earlier instance its metadata names (`meta.basis` `formal_relation`), else the ECLI or the case number and date its text names (`referral_text`). |
| `SCOPED_BY` | Article | Annex | An article whose scope is defined by an annex. |
| `ABOUT` | Activity / Decision / Commitment | Case / Dossier | The subject of an activity, decision or commitment: Activity/Decision → Case; Commitment → Dossier. |
| `LED_BY` | Activity | Committee | The lead committee (`voortouwcommissie`) of an activity; absent for plenary. |
| `MADE_IN` | Commitment | Activity | The activity in which a commitment (toezegging) was made. |
| `MEMBER_OF` | Member | Committee / Faction | Membership of a committee or faction, with from/to dates and role. |
| `AUTHORED` | Member | Document / Case | A person signed or submitted a document or case; `role` says how (first signatory, co-signatory, …), `function` as what (`Functie`) and `capacity` in which capacity (`kamerlid`, `bewindspersoon`, `overig`). |
| `RELATED_TO` | Dossier | Dossier | The Kamer relates a case of this dossier to a case of the other (`Zaak.GerelateerdNaar`), mostly a letter of the government to the motion it answers; `meta.cases` counts the pairs of cases, `meta.case_kinds` names them. |
| `REVISES` | Dossier | Dossier | A supplementary budget or a slotwet revises the budget of its chapter and year (`meta.rule`: `begrotingswijziging` or `slotwet`). |
| `ACCOMPANIES` | Dossier | Dossier | A budget change is submitted with the Voorjaarsnota, Najaarsnota or Miljoenennota (`meta.nota`) that its title names. |
| `VOTED` | Member / Faction | Decision | A vote on a decision: per member for roll-call votes, per faction otherwise (`choice`, `seats`). |

<!-- relations:end -->

## Keys

| Collection | Key |
|------------|-----|
| `instruments` (BWB) | `bwbr0001854` (`bwb_id`; treaties `bwbv...`) |
| `instruments` (EU) | `32016l0680` (`celex`) |
| `instruments` (Verdragenbank treaty) | `verdrag_<id>` |
| `instruments` (amending publication) | `stb_2019_33` (publication identifier) |
| `instruments` (ECHR Convention) | `echr_convention` |
| `articles` | `<bwb_id>_<article_number>` (a book of the Burgerlijk Wetboek is a regulation of its own: `bwbr0005289_162` is 6:162 BW); EU `<celex>_<article_number>`; historical `<bwb_id>_<number>_stam_<stam_id>`; ECHR `echr_convention_<n>` |
| `instrument_versions` | `<bwb_id>_<valid_from>` |
| `article_versions` | `<bwb_id>_av_<stam_id>_<versie_id>` |
| `annexes` | `<bwb_id>_annex_<label>` (`<bwb_id>_annex` without a label) |
| `judgments` | `ecli_nl_hr_2023_1234`; ECHR `echr_<itemid>` |
| `dossiers` | `<number>` or `<number>_<suffix>` |
| `cases`, `documents` (TK), `activities`, `commitments`, `committees`, `members` | TK GUID (`Id`); a member only Wikidata knows `wikidata_q<number>` |
| `documents` (other) | `stb_<identifier>`, `stcrt_<identifier>`, `ek_<id>` |
| `decisions` | `stemming_<Besluit_Id>` |
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
| `section_anchor` | `id` of the surest section (`props.sections` of the Document); `heading`, `char_start`, `char_end` and `match_type` are that section's |
| `match_type` | `heading_target`, `body_named_law`, `own_number` or `inferred_law` (`docs/pipelines.md`) |
| `sections` | every section that explains the article, in document order: `section_anchor`, `heading`, `char_start`, `char_end`, `match_type`, `confidence` |

`char_start`/`char_end` are offsets into `props.text` of the Document.

Semantic layer on article-to-article `REFERS_TO` edges, orthogonal to `relation`: `relation`
says that two articles are linked, `semantic_type` says what the link means.

| Field | Values |
|-------|--------|
| `semantic_type` | `conditional_requirement`, `scope_limitation`, `prerequisite_procedure`, `definitional_reference`, `limiting_exception`, `cross_reference`, `delegated_discretion`; null for unclassified edges |
| `explanation` | the pattern that decided the type, in words |
| `updated_at` | when the classification last changed |
| `meta.semantic_pattern`, `meta.semantic_confidence` | audit trail of the extraction |

## Instrument

An instrument is any rule with a basis in a power laid down in law. It is not limited to
statutes made by the legislator:

- BWB types ingested (`BWB_INSTRUMENT_TYPES`): `wet`, `rijkswet`, `AMvB`, `rijksAMvB`, `KB`,
  `rijksKB`, `ministeriele-regeling`, `ministeriele-regeling-archiefselectielijst`, `zbo`,
  `pbo`, `reglement`, `beleidsregel`, `verdrag`, and the `-BES` variants of `wet`, `AMvB`,
  `ministeriele-regeling` and `beleidsregel`. `circulaire` is not ingested.
- A BWB regulation also carries what its toestand says other steps link from: `basis` (the
  `Gelet op` references: `bwb_id`, `article`, `doc`, `text`) and `celex_refs` (the EU acts its
  text names, which is also what `retrieve eurlex --mode gaps` fetches). One Celex link in
  eight has an id with an impossible year in the source; it is rebuilt from the text of the
  link ("verordening (EU) 2021/784") or left out.
- Treaties are instruments, both BWB treaties (`BWBV...`) and Verdragenbank records.
- EU directives, regulations and decisions (`celex`).
- The Convention of the ECHR (`echr_convention`): kind `verdrag`, `bwb_id` `ECHR-CONVENTION`, which its articles carry too.
- Amending publications (Staatsblad, Tractatenblad, ...) are instruments too
  (`publication_kind`, `publication_year`, `publication_number`, `date_signed`,
  `date_published`, `dossier_numbers`); they are the source of `AMENDS`, `INTRODUCES` and
  `REPEALS`.

An instrument that amends, introduces or repeals has enacted the change (`status: canoniek`).
A bill (Document) carries the same three relations with `status: voorgesteld` — a change it
proposes. Only an instrument is based on a basis article or implements a directive, and only a
document (memorie van toelichting, nota van toelichting) explains.

## Article and versions

BWB identifies an article by `stam-id`, which stays the same across versions and
renumbering; each version has a `versie-id`.

| Node | Identity | Notes |
|------|----------|-------|
| Article | one per `(bwb_id, article_number)` for the current text; historical identities per `stam_id` | props: `stam_id`, `versie_id`, `valid_from` (`inwerking`), `source_publication` (`bron`), `repealed`, `parts`, `references`, `breadcrumb` (see below) |
| ArticleVersion | one per `(stam_id, versie_id)`, not per toestand | `valid_from` = the article's own `inwerking`; `valid_until` = `valid_from` of the next version of the same article, null when current; `current`; `effect` (`nieuw`, `wijziging`, `vervallen`, ...); `source_publication`; `parts`; `origin_publication` and `commencement_publication` (id, kind, year, number, effect, signed, published, dossiers) |
| InstrumentVersion | one per toestand `(bwb_id, valid_from)` | `valid_from`, `valid_until`, `current`, `state_url` |

- `ArticleVersion VERSION_OF Article` and `InstrumentVersion VERSION_OF Instrument`. There are
  no membership or succession edges: "the article on date X" is the version with
  `valid_from <= X` and (`valid_until > X` or null).
- Historical articles are identities that are not in the current toestand. They have no
  `article_number` (`(bwb_id, article_number)` is a unique index); the last known number is
  in `last_article_number`. They carry `repealed: true`.
- `repealed` is also set on a current article whose latest `effect` is `vervallen`.
- Articles of the current toestand without a number or without text are not written.
- `parts` is the structure of the text: a list of `{id, kind, number, start, end}`, offsets into
  the article's own `text` (the text of a part is `text[start:end]`, without its printed
  number). `kind` is `lid`, `onderdeel` or `aanhef`; sentences (volzinnen) are not parts. A
  part with onderdelen spans them too, and the list is ordered by `start`, an enclosing part
  first. The `id` is stable and unique in the article: `lid-2`, `lid-2a`, `lid-2-aanhef` (the
  text of a lid before its onderdelen), `lid-2-onder-a`, `lid-2-onder-a-onder-1` (an onderdeel
  of an onderdeel), and for an article without leden `aanhef` and `onder-a`. Numbers are
  written lower case without the degree sign (`1°` is `onder-1`; `number` keeps `1°`). An
  item without a letter or digit (a dash, a definition) is `onder-_<n>`, its position among
  its siblings; a marker that repeats one before it gets `_<n>`, its occurrence
  (`onder-a_2`). A paragraph next to the leden is no part.
- `breadcrumb` is where the article stands in its regulation, outermost first:
  `{type, label, title}` per division that holds it, `type` the element of the toestand
  (`boek`, `deel`, `titeldeel`, `hoofdstuk`, `afdeling`, `paragraaf`, `sub-paragraaf`,
  `divisie`), `label` as printed (`Hoofdstuk 1`, `Titel 1.1`), `title` its heading. Absent for
  an article outside every division.
- `references` holds every `extref`/`intref` of the text that names a regulation:
  `{kind, bwb_id, article, doc, text, start, end, leden, onderdelen, aanhef}`. The `doc` (JCI)
  of a BWB link stops at the article, so `leden`, `onderdelen` (written as in the part ids)
  and `aanhef` are read from the text of the link (`core/qualifiers.py`); a link to a chapter
  or a title has none.

## Judgment

A Rechtspraak judgment carries its header (`court`, `date`, `case_number`, `judgment_metadata`
with `type`, the procedure, and `document_type`, `Uitspraak` or `Conclusie`, `related_eclis`
(earlier instances), `conclusion_eclis` (its conclusion, or the judgment of a conclusion),
`subjects`; `court_code`, `tier`, `date_eff` and `case_number_keys`, the case numbers as compared,
derived), `summary`, `text` and `paragraphs`.

The judgments of one case are tied by `APPEAL_OF` (an appeal to the judgment it appeals),
`ADVISES_ON` (a conclusion to its judgment) and `ANSWERS` (a preliminary ruling to the decision
that asked its questions); `docs/pipelines.md`, Rechtspraak, says how each is found.

Parallel cases a court decided on one day in (nearly) the same words form a series: each
judgment of it has `series_id`, the lowest ECLI in the series, and `series_size`; outside a
series both are null (`semantic rechtspraak-series`). A series has no edges.

`paragraphs` is the `<uitspraak>` in reading order, a list of `{id, number, kind, text}`. `kind` is
`heading` (a section), `subheading` (a nested section, or an `<uitspraak.info>` block) or `body`.
A numbered unit of the XML (`<paragroup>`, however deeply nested) is one `body` paragraph with
its own text: the text of `5.3` does not hold `5.3.1`. Where the XML has no such structure a
`<para>` is a paragraph, and a number that its text opens with (`1.    Bij het besluit`) is its
number. `number` is the number as printed without its closing dot (`5.3`), null when there is
none, and is not part of `text`. `id` names the paragraph in deep links and mentions and is
unique in the judgment: `rov-5.3` for a numbered `body` paragraph (a consideration, cited as
"rov. 5.3"), `kop-5` for a numbered heading, `p-<n>` (its position) for a paragraph without a
number; a number that repeats one before it gets `_<n>`, its occurrence (`rov-1_2`).

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

Dossier contains Case contains Document. TK data is the source.

| Concept | Collection | Notes |
|---------|-----------|-------|
| Dossier | `dossiers` | `number`, `suffix`, `label` (`37020-XV`; the key is made from it), `title`, `title_source`; derived: `opened_on` (first document or activity), `case_kinds` (the `Zaak.Soort` of the dossier's own cases), `track_kind` (what the dossier is, never what is filed under it: a bill `wetsvoorstel`, `initiatiefwetsvoorstel`, `begroting` (also a slotwet) or `verdrag` by its own case or bill; `initiatiefnota`; `nota`, a paper of the government that is itself the subject, named so in the title: the Miljoenennota "Nota over de toestand van ’s Rijks Financiën", the Voorjaars- and Najaarsnota, the Financieel Jaarverslag van het Rijk, a Defensienota, the HGIS-nota; otherwise `overig`, the letters and motions on a subject such as an EU Council series), `same_number_count` (the other dossiers with the same number, written by `normalize tk-dossiers`), `current_stage`, `stages_present`, `stages_missing` (the stages passed on the way to the current one, those the track always passes included, without a dated document, activity or vote; see [pipelines](pipelines.md)) and `stages_complete` (none missing); of `wetsvoorstel`, `mvt`, `advies_rvs`, `verslag`, `nota_naar_aanleiding_van_verslag`, `amendementen`, `behandeling`, `stemming`, `afgehandeld`; the first eight for a bill only); `closed`, `outcome` (`aangenomen`: its law was published; `ingetrokken`: its bill was withdrawn by letter; `verworpen`: the Tweede Kamer voted the bill down) and `closed_on`, derived from the graph by `semantic tk-dossier-outcomes` (the TK record has no end of its own). An open dossier has `closed: false` and no outcome |
| Case | `cases` | every TK Zaak, no filter on kind; `title`, `citation_title`, `number`, `kind` (`Zaak.Soort`), `dossier_numbers`, `related_cases` (`Zaak.GerelateerdNaar`: `id`, `kind`, `dossier_numbers` of each case the Kamer relates it to; read by `semantic tk-dossier-relations`) (the payload stays in `raw_sources`) |
| Document | `documents` | TK Document (`kind`, `title`, `subject`, `date`, `sequence`, `session_year`, `document_number` (`DocumentNummer`), `dossier_numbers`, `case_ids`, `case_kinds`, `actors`, `text`; the structure of the text of a Kamerstuk XML: see below); also Staatsblad, Staatscourant and Eerste Kamer documents (`ek_<identifier>`, `dossier_number`, `dossier_suffix`, and the label in `dossier_numbers` as on a TK document); the chamber is in `labels` (`TK`; `EersteKamer` and `EK`), and a `kind` containing `toelichting` makes a document explanatory |
| Activity | `activities` | debate or hearing; `number` (`Activiteit.Nummer`), `date`, `agenda_title` (`Onderwerp`), `kind`, `status` (`Gepland`, `Uitgevoerd`, `Geannuleerd`, `Verplaatst`, `Vervallen`), `committee_id` (null for a plenary activity), `case_ids`, `dossier_numbers`, `case_kinds_by_dossier` |
| Decision | `decisions` | one node per TK `Besluit`; `primary_case_id` and `primary_case_kind` name the Zaak it decided (`Wetgeving` on the vote on a bill itself) |
| Commitment | `commitments` | `status` mapped to `open`, `gedaan`, `vervallen`, `unknown`; `activity_number` |
| Member | `members` | every TK `Persoon` (members and ministers; a minister who never sat in parliament has no name or date of birth there); `name`, `family_name`, `birth_date`, `party`, `faction_memberships` (dated timeline); from Wikidata `wikidata_id`, `wikidata_name` and `government_functions` (`function`, `cabinet`, `from_date`, `to_date`, and the Q-ids `position_id`, `cabinet_id`: every post in a Dutch cabinet). A cabinet member without a TK `Persoon` is a member of its own, label `Wikidata`, key from the Q-id |
| Faction | `factions` | `name`, `abbreviation`, `aliases`, `seats`, `active` |
| Committee | `committees` | `name`, `abbreviation`, `slug`; only a Commissie with a name (the plenary is no committee) |

No link to tweedekamer.nl is stored. The site finds a document by its `document_number` and an
activity by its `number`, never by the GUID of the record (`external_id`), so the API derives
`tk_url` from those when it answers (`core/tk_links.py`): a template that turns out wrong is
fixed by a release, not by a migration. The Eerste Kamer papers keep the `url` of their page on
officielebekendmakingen.nl as the source gives it.

Dossiers of different numbers are tied by three edges, written by `semantic
tk-dossier-relations` (the rules: [pipelines](pipelines.md#semantic-tk-dossier-relations)):
`REVISES` (a supplementary budget or slotwet → the budget of its chapter and year), `ACCOMPANIES`
(a budget change → the Voorjaarsnota, Najaarsnota or Miljoenennota it is submitted with) and
`RELATED_TO` (the Kamer relates a case of the one to a case of the other). The dossiers of one
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
and `passed`; each edge carries `meta.choice` and `meta.seats`. The API derives a member's
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

`MEMBER_OF` edges run from a member to a committee (`meta` = the seat's period) and to a
faction (`meta.from_date`, `meta.to_date`, `meta.role`). Edge keys are one per pair, so a
member who leaves and rejoins keeps one edge with the latest period; the full timeline is in
`members.props.faction_memberships`.

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
| `tk` | `tk-zaak`, `tk-document`, `tk-dossier`, `tk-activiteit`, `tk-stemming`, `tk-toezegging`, `tk-commissie`, `tk-persoon`, `tk-fractie`, `tk-fractie-zetel-persoon`, `tk-kamerstuk-xml` (the XML of a paper, external id `kst-<dossier>-<n>`, `meta.document` the key of its Document) |
| `rechtspraak` | `rs-content` |
| `eurlex` | `eu-celex-html` |
| `bwb` | `bwb-toestand-xml` (current), `bwb-toestand-xml-all` (every toestand, external id `<bwb_id>@<start_date>`), `bwb-wti-algemene-informatie-xml` (the first element of the WTI file: official abbreviations, citation titles, legal areas) |
| `staatsblad` | `stb-amvb-xml` |
| `staatscourant` | `stcrt-regeling-xml` |
| `eerstekamer` | `ek-kamerstuk-json` |
| `echr` | `echr-judgment-json` |
| `verdragenbank` | `verdrag-json` |
| `wikidata` | `wikidata-cabinet-posts-json` (one person and every post they held in a Dutch cabinet, external id the Q-id) |

A document the source answered HTTP 404 for is remembered as a record without payload of
kind `<kind>-missing` (`eu-celex-html-missing`, `rs-content-missing`, ...); the retrieve
pipelines do not ask for it again for 30 days (3 days for a Kamerstuk of the last week, whose
XML is still to be published) and no other phase reads it.

## Indexes and search views

Defined in `db/schema.py`, created when `ArangoStore` starts.

| Collection | Indexes |
|------------|---------|
| `instruments` | unique sparse `props.bwb_id`, `props.celex`; `props.jurisdiction`, `props.kind`, `props.article_count`, `props.citation_title` |
| `articles` | unique sparse `(props.bwb_id, props.article_number)` and `(props.celex, props.article_number)`; sparse `props.bwb_id` and `props.celex` (a compound sparse index cannot answer the first field alone: an article without a number is not in it); `(props.bwb_id, props.stam_id)`; `props.inbound_citation_count`; `labels[*]` |
| `instrument_versions`, `article_versions` | `(bwb_id, valid_from)`, `(bwb_id, current)`, `(bwb_id, stam_id)`, `(bwb_id, article_number, valid_from)`, `(bwb_id, article_number, current)` |
| `judgments` | unique sparse `props.ecli`; sparse `props.appno`; sparse `props.case_number_keys[*]`; sparse `props.series_id`; `props.source`, `court_code`, `tier`, `date_eff`, `inbound_citation_count`; `(stub, source, tier, court_code, court, date_eff)`, which answers the coverage of `/api/stats/coverage` alone; `labels[*]` |
| `documents`, `dossiers`, `activities`, `decisions`, `commitments`, `annexes` | the fields the list endpoints filter and sort on |
| `raw_sources` | `(source, kind)` |
| `edges` | `relation`; `(_from, relation)`; `(_to, relation)`; `status`; `(status, relation)`; `confidence`; `semantic_type`; `(_from, semantic_type)` |

An index that is sorted on (`SORT ... LIMIT`) or counted per value (`edges.relation`,
`props.source`, `props.kind`, `props.jurisdiction`, `raw_sources (source, kind)`) is not
sparse: a sparse index leaves out documents without a value, so the optimiser may not use
it for a sort or a count and reads every document instead. `created_at` on edges is
deliberately not indexed.

ArangoSearch views back `/api/search`: `search_articles`, `search_instruments`,
`search_judgments`, `search_dossiers`, `search_documents`, `search_committees`, using the
analyzers `lawgraph_ngram_v2` (lower-cased 3-12 character n-grams, so `vordering` finds
`Strafvordering`) and `lawgraph_norm` (lower-cased identity for identifiers), plus `identity`
and the Dutch `text_nl` (`TEXT_ANALYZER`: a word is stemmed, so `uitspraken` finds `uitspraak`;
English texts such as ECHR summaries are stemmed as Dutch too). Views fill asynchronously; a
fresh insert may be missing briefly. `members` and `factions` have no view: they are small
enough to scan.

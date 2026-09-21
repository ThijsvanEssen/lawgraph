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
  `member`, `faction`, `committee`, `topic`).
- `labels` tag the origin (`BWB`, `EU`, `TK`, `Rechtspraak`, `ECHR`, `EersteKamer`, ...). Upserts
  union labels.
- `props` are validated against a strict Pydantic schema per collection (`core/props.py`);
  unknown fields are rejected. Upserts merge props (shallow), so several pipelines can add
  fields to one node.
- `stub: true` marks a placeholder created because something referred to it before its own
  source was ingested.

Other collections: `raw_sources` (verbatim payloads), `watches` (saved node watches, not
scoped to a user), `edge_status_log` (audit rows written by `ArangoStore.flip_edge_status`,
which no pipeline calls), `topics` (schema only; nothing writes it).

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
| `IMPLEMENTS` | Instrument | Instrument | A national instrument transposes an EU directive. |
| `LEGISLATED_IN` | Instrument | Dossier | The parliamentary dossier in which an instrument was legislated (BWB `dossierref`). |
| `REFERS_TO` | Article / Document / Judgment | Article / Instrument / Judgment | A text refers to an article, instrument or judgment. The source node says who refers; article → article edges also carry a `semantic_type`. |
| `EXPLAINS` | Document | ArticleVersion / Article / Instrument | A document (MvT, NvT) explains the article version or instrument it introduced or changed. |
| `APPEAL_OF` | Judgment | Judgment | An appeal or cassation judgment → the judgment it appeals. |
| `SCOPED_BY` | Article | Annex | An article whose scope is defined by an annex. |
| `ABOUT` | Activity / Decision / Commitment | Case / Dossier | The subject of an activity, decision or commitment: Activity/Decision → Case; Commitment → Dossier. |
| `LED_BY` | Activity | Committee | The lead committee (`voortouwcommissie`) of an activity; absent for plenary. |
| `MADE_IN` | Commitment | Activity | The activity in which a commitment (toezegging) was made. |
| `MEMBER_OF` | Member | Committee / Faction | Membership of a committee or faction, with from/to dates and role. |
| `AUTHORED` | Member | Document / Case | A person signed or submitted a document or case; `role` says how (first signatory, co-signatory, minister, …). |
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
| `articles` | `<bwb_id>_<article_number>`; EU `<celex>_<article_number>`; historical `<bwb_id>_<number>_stam_<stam_id>`; ECHR `echr_convention_<n>` |
| `instrument_versions` | `<bwb_id>_<valid_from>` |
| `article_versions` | `<bwb_id>_av_<stam_id>_<versie_id>` |
| `annexes` | `<bwb_id>_annex_<label>` (`<bwb_id>_annex` without a label) |
| `judgments` | `ecli_nl_hr_2023_1234`; ECHR `echr_<itemid>` |
| `dossiers` | `<number>` or `<number>_<suffix>` |
| `cases`, `documents` (TK), `activities`, `commitments`, `committees`, `members` | TK GUID (`Id`) |
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
| `status` | `canoniek` (default) or `voorgesteld` — a change a bill proposes but has not enacted, written by `amendment-articles` and by the `AMENDS` half of `instrument-relations` |
| `confidence` | 0-1; absent on structural edges; 1.0 when read from source XML |
| `created_at` | set on insert only |
| `meta` | evidence and context: `start`, `end`, `text`, `raw_match`, `snippet` (300 characters around the match), `reason`, `qualifier`, `effective_date`, `article_version`, `scope_type`, ... Upserts merge `meta` |

Semantic layer on article-to-article `REFERS_TO` edges, orthogonal to `relation`: `relation`
says that two articles are linked, `semantic_type` says what the link means.

| Field | Values |
|-------|--------|
| `semantic_type` | `conditional_requirement`, `scope_limitation`, `prerequisite_procedure`, `definitional_reference`, `limiting_exception`, `cross_reference`, `delegated_discretion`; null for unclassified edges |
| `semantic_source` | `structured` (pattern extraction), `expert`, `community`, `llm` |
| `explanation`, `expert_badge`, `created_by`, `updated_at` | curation metadata |
| `community_upvotes`, `community_downvotes` | counters |
| `meta.semantic_pattern`, `meta.semantic_confidence` | audit trail of the extraction |

Re-running the pipelines never overwrites `expert` or `community` classifications.

## Instrument

An instrument is any rule with a basis in a power laid down in law. It is not limited to
statutes made by the legislator:

- BWB types ingested (`BWB_INSTRUMENT_TYPES`): `wet`, `rijkswet`, `AMvB`, `rijksAMvB`, `KB`,
  `rijksKB`, `ministeriele-regeling`, `ministeriele-regeling-archiefselectielijst`, `zbo`,
  `pbo`, `reglement`, `beleidsregel`, `verdrag`, and the `-BES` variants of `wet`, `AMvB`,
  `ministeriele-regeling` and `beleidsregel`. `circulaire` is not ingested.
- Treaties are instruments, both BWB treaties (`BWBV...`) and Verdragenbank records.
- EU directives, regulations and decisions (`celex`).
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
| Article | one per `(bwb_id, article_number)` for the current text; historical identities per `stam_id` | props: `stam_id`, `versie_id`, `valid_from` (`inwerking`), `source_publication` (`bron`), `repealed`, `references` (structured `extref`/`intref` with text offsets) |
| ArticleVersion | one per `(stam_id, versie_id)`, not per toestand | `valid_from` = the article's own `inwerking`; `valid_until` = `valid_from` of the next version of the same article, null when current; `current`; `effect` (`nieuw`, `wijziging`, `vervallen`, ...); `source_publication`; `origin_publication` and `commencement_publication` (id, kind, year, number, effect, signed, published, dossiers) |
| InstrumentVersion | one per toestand `(bwb_id, valid_from)` | `valid_from`, `valid_until`, `current`, `state_url` |

- `ArticleVersion VERSION_OF Article` and `InstrumentVersion VERSION_OF Instrument`. There are
  no membership or succession edges: "the article on date X" is the version with
  `valid_from <= X` and (`valid_until > X` or null).
- Historical articles are identities that are not in the current toestand. They have no
  `article_number` (`(bwb_id, article_number)` is a unique index); the last known number is
  in `last_article_number`. They carry `repealed: true`.
- `repealed` is also set on a current article whose latest `effect` is `vervallen`.
- Articles of the current toestand without a number or without text are not written.

## Parliament

Dossier contains Case contains Document. TK data is the source.

| Concept | Collection | Notes |
|---------|-----------|-------|
| Dossier | `dossiers` | `number`, `suffix`, `title`, `title_source`, `closed`, `opened_on`, `closed_on`; derived: `current_stage`, `stages_present` (of `wetsvoorstel`, `mvt`, `advies_rvs`, `nota`, `verslag`, `amendementen`, `stemming`, `afgehandeld`), `case_kinds`, `track_kind` (`wetsvoorstel`, `initiatiefwetsvoorstel`, `begroting`, `motie`, `overig`), `outcome` (`aangenomen`, `verworpen`, `ingetrokken` for closed dossiers) |
| Case | `cases` | every TK Zaak, no filter on kind; `title`, `citation_title`, `number`, `dossier_numbers` (the payload stays in `raw_sources`) |
| Document | `documents` | TK Document (`kind`, `title`, `subject`, `date`, `sequence`, `session_year`, `dossier_numbers`, `case_ids`, `actors`, `text`); also Staatsblad, Staatscourant and Eerste Kamer documents (`ek_<identifier>`, `dossier_number`, `dossier_suffix`) |
| Activity | `activities` | debate or hearing; `date`, `agenda_title`, `kind`, `committee_id`, `case_ids`, `dossier_numbers` |
| Decision | `decisions` | one node per TK `Besluit` |
| Commitment | `commitments` | `status` mapped to `open`, `gedaan`, `vervallen`, `unknown`; `activity_number` |
| Member | `members` | every TK `Persoon` (members and ministers); `name`, `party`, `faction_memberships` (dated timeline) |
| Faction | `factions` | `name`, `abbreviation`, `aliases`, `seats`, `active` |
| Committee | `committees` | `name`, `abbreviation`, `slug` |

Votes: TK returns one row per voter per `Besluit`. A roll-call (`Hoofdelijk`) names every
member, so its `VOTED` edges start at the member; any other vote is cast per faction and the
edge starts at the faction. The decision carries `vote_kind` (`member` or `faction`), `tally`
(seats per choice, members per choice on a roll-call), `voters` (how many cast each choice)
and `passed`; each edge carries `meta.choice` and `meta.seats`. The API derives a member's
non-roll-call votes from the faction they belonged to at the time, using
`members.props.faction_memberships`.

Authorship is stored on the document (`props.actors` with `person_id`, `faction_id`, `name`,
`faction`, `role`) and as `AUTHORED` edges from the signatory, with `meta.role`. Only people
get an edge; which faction signed follows from the signatory's faction membership.

`MEMBER_OF` edges run from a member to a committee (`meta` = the seat's period) and to a
faction (`meta.from_date`, `meta.to_date`, `meta.role`). Edge keys are one per pair, so a
member who leaves and rejoins keeps one edge with the latest period; the full timeline is in
`members.props.faction_memberships`.

## raw_sources

`{_key, source, kind, external_id, fetched_at, payload_json, payload_text, meta}`.
JSON sources use `payload_json`; XML and HTML sources use `payload_text`.

| Source | Kinds |
|--------|-------|
| `tk` | `tk-zaak`, `tk-document`, `tk-dossier`, `tk-activiteit`, `tk-stemming`, `tk-toezegging`, `tk-commissie`, `tk-persoon`, `tk-fractie`, `tk-fractie-zetel-persoon` |
| `rechtspraak` | `rs-content` |
| `eurlex` | `eu-celex-html` |
| `bwb` | `bwb-toestand-xml` (current), `bwb-toestand-xml-all` (every toestand, external id `<bwb_id>@<start_date>`), `bwb-wti-algemene-informatie-xml` (the first element of the WTI file: official abbreviations, citation titles, legal areas) |
| `staatsblad` | `stb-amvb-xml` |
| `staatscourant` | `stcrt-regeling-xml` |
| `eerstekamer` | `ek-kamerstuk-json` |
| `echr` | `echr-judgment-json` |
| `verdragenbank` | `verdrag-json` |

A document the source answered HTTP 404 for is remembered as a record without payload of
kind `<kind>-missing` (`eu-celex-html-missing`, `rs-content-missing`, ...); the retrieve
pipelines do not ask for it again for 30 days and no other phase reads it. A Kamerstuk without
XML is remembered on the document itself (`props.text_missing_at`).

## Indexes and search views

Defined in `db/schema.py`, created when `ArangoStore` starts.

| Collection | Indexes |
|------------|---------|
| `instruments` | unique sparse `props.bwb_id`, `props.celex`; `props.jurisdiction`, `props.kind`, `props.article_count`, `props.citation_title` |
| `articles` | unique sparse `(props.bwb_id, props.article_number)` and `(props.celex, props.article_number)`; `(props.bwb_id, props.stam_id)`; `props.inbound_citation_count`; `labels[*]` |
| `instrument_versions`, `article_versions` | `(bwb_id, valid_from)`, `(bwb_id, current)`, `(bwb_id, stam_id)`, `(bwb_id, article_number, valid_from)`, `(bwb_id, article_number, current)` |
| `judgments` | unique sparse `props.ecli`; sparse `props.appno`; `props.source`, `court_code`, `tier`, `date_eff`, `inbound_citation_count`; `labels[*]` |
| `documents`, `dossiers`, `activities`, `decisions`, `commitments`, `annexes`, `watches` | the fields the list endpoints filter and sort on |
| `raw_sources` | `(source, kind)` |
| `edges` | `relation`; `(_from, relation)`; `(_to, relation)`; `status`; `(status, relation)`; `confidence`; `semantic_type`; `(_from, semantic_type)`; `semantic_source` |
| `edge_status_log` | `timestamp`, `edge_key` |

Sort-key indexes are non-sparse so `SORT ... LIMIT` is served from the index. `created_at` on
edges is deliberately not indexed.

ArangoSearch views back `/api/search`: `search_articles`, `search_instruments`,
`search_judgments`, `search_dossiers`, `search_documents`, `search_committees`, using the
analyzers `lawgraph_ngram_v2` (lower-cased 3-12 character n-grams, so `vordering` finds
`Strafvordering`) and `lawgraph_norm` (lower-cased identity for identifiers), plus `text_en`
and `identity`. Views fill asynchronously; a fresh insert may be missing briefly. `members` and
`factions` have no view: they are small enough to scan.

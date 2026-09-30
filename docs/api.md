# API

A FastAPI service over the graph (`lawgraph.api.app:app`); it only reads. Start it with
`lawgraph-api` (uvicorn, `LAWGRAPH_API_HOST`:`LAWGRAPH_API_PORT`, default `127.0.0.1:8000`; set the host to `0.0.0.0` to serve other machines) or
`uvicorn lawgraph.api.app:app --reload`. The interactive schema is at `/docs`, the machine
schema at `/openapi.json`: every route has a summary, a tag and a typed answer, and every
route is a `GET` (`tests/api/test_openapi_schema.py` holds the schema to that), so a client
can generate its types from it.

## Endpoints

Paths are relative to the host. `bwb_id` is a BWB id (`BWBR0001854`) and `article_number` the
address of an article (its `address`): the number as the graph stores it (`287`, `8:54` of the
Awb, `bijlage 2 artikel 9` for an article of an annex, URL-encoded), or, for an article without a
number, the rest of its key (`stam_16464063`, the Algemene bepaling of the Grondwet; a repealed
identity `2_10_stam_2866303`), which stays across versions; an instrument
route takes `bwb_id` or a CELEX number (`32016L0680`) for an EU act, in any case. A dossier `number`
matches `^\d+(-[A-Za-z0-9()]+)?$` (`29684`, `29684-I`, `21501-31`, `36956-(R2220)`), otherwise 422. A budget chapter is a dossier
of its own: `37020-XV` is not `37020`. Every dossier number the API returns (`number` of a
dossier, `dossier_number`, `dossier_numbers`, in either chamber) is written this way, so it can be used in a path
or a `dossier` filter as it is. List parameters `limit` and `offset` have the bounds shown in
`/docs`. Every paged list has a total order (its sort ends in a unique key, or reads an index
that orders ties by key), so walking its pages gives each row once.

The periods of articles and versions are half-open: `valid_until` is the first day a version is no longer in force (the start of the next), so `2021-07-01` means up to and including 2021-06-30, the "t/m 30-06-2021" of wetten.overheid.nl. An open period has `valid_until` null.

The periods of members and factions follow the Tweede Kamer and are inclusive: `to_date` (of a faction membership, a committee seat, a faction's `active_until`) is the last day, the Kamer's `TotEnMet`. Two successive periods touch: one ends the day before the next begins. An open period has `to_date` null.

Articles, their versions, instruments, their versions and publications carry `official_url`,
the official text (`core/official_urls.py`): an article on wetten.overheid.nl by its JCI
(`jci1.3:c:{BWB}&artikel={nr}`, with `&g={valid_from}` for a version; the regulation for an
article without a number the JCI can address), a BWB regulation as `/{BWB}` (a version
`/{BWB}/{valid_from}`), an EU act on EUR-Lex by its CELEX number, a treaty on the
Verdragenbank, a Staatsblad, Staatscourant or Tractatenblad publication on
zoek.officielebekendmakingen.nl (`stb-2019-33`; null before 1995, where that site begins).

### Service

| Method | Path | Response |
|--------|------|----------|
| GET | `/` | `{"name": "lawgraph-api", "version": ...}` |
| GET | `/api/health` | `{"status": "ok", "database": "connected"}`, 503 when the database is unreachable |
| GET | `/api/stats` | `nodes`: document count without stubs of `instruments` (without the publications), `publications` (the Staatsblad, Staatscourant and Tractatenblad publications), `articles`, `judgments`, `documents`, `cases`, `dossiers`, `activities`, `decisions`, `commitments`, `committees`, `members` and `cabinets` (not `factions`, `annexes`, `instrument_versions` or `article_versions`); `stubs`: per collection that has them (`instruments`, `articles`, `judgments`) the nodes known only because something refers to them; `edges`: `total` and `by_relation`; `by_source`: `judgments` and `documents` per `props.source`; `instruments`: `by_kind` and `by_jurisdiction` (publications included); `data_as_of`: per source (`tk`, `eerstekamer`, `rechtspraak`, `staatsblad`, `staatscourant`, `bwb`, `eurlex`, …) `retrieved_at` (when its newest raw record was fetched) and `newest` (the date of its newest dated record on or before today: a paper, a judgment, a publication, a version coming into force; null for a source without dated records), read at most once a minute |
| GET | `/api/stats/coverage` | the judgments whose text is loaded: `total`, `first_date`, `last_date`, per tier (`tiers`: `tier`, `count`, `first_date`, `last_date`, in the order of `core.courts.TIERS`: the highest courts, the parket, the courts of first instance and appeal, the disciplinary tribunals, the other colleges, the Caribbean part, then the courts outside the Netherlands, the EHRM last) and per court (`courts`: `source`, `tier`, `court_kind`, `court_code`, `court`, `count`, `first_date`, `last_date`, most first), and `stubs`, the judgments known only because a loaded one cites them. Every count of judgments in the API counts this selection, not the case law |

### Articles

| Path | Returns |
|------|---------|
| `/api/articles/{bwb_id}/{article_number}` | (`article_number` of a book of the BW may carry its book: `6:162` under BWBR0005289 is article 162, on every article route) the article (with `label`, `heading`, `address`, `repealed`) with its `parts` (aanhef, leden and onderdelen as spans of `text`; an EU article, addressed by its CELEX number, has them too, with the heading under its number), its instrument (`bwb_id`, `celex`, `title`, `citation_title`, `short_title`, `display_name`), citing judgments, `citations` (the resolved references, one per target), `references` (every reference in the text, with the `leden`, `onderdelen` and `aanhef` it names, also when the target is not in the graph), and its relationships: `upstream_dependencies` (outgoing references) and `downstream_implications` (incoming ones), each with `semantic_type`, its explanation and confidence, the span of the reference (`start`, `end`, `text`, in the referring article) and the `leden`, `onderdelen` and `aanhef` it names, and `scope_articles` (annex scopes) |
| `.../history` | every version of the article, oldest first (only the last is `current`; empty for a law whose toestanden `retrieve bwb-history` has not loaded): validity period, text, `effect`, normalized `change` (`introduces`, `amends`, `repeals`, `republishes`: the text placed again unchanged), amending publication (`amended_by`) and commencement publication, each with its dossiers and its `parts`. The article is identified by `stam_id`, so renumbering does not break history; an article of a bijlage, which has none, by its number, with a version per text; 404 for an unknown article |
| `.../legislative-history` | the dossiers that introduced, amended or repealed the article, or propose to: one entry per change and dossier (`dossier_id`, null for a dossier a publication names that is not in the graph, `dossier_number`, `dossier_title`, `change` `introduces`/`amends`/`repeals`, `status` `canoniek` for an amending publication, `voorgesteld` for a bill, `document_id`, `kind`, `date`, `summary` of that publication or bill), proposed first, then newest first. What only cites the article (a judgment, another article) is no history; the explanatory documents are at `explained-by`; empty list, never 404 |
| `.../explained-by` | the documents that `EXPLAINS` the article: edges to the article or to any of its versions (same `stam_id`); an edge to its law as a whole says nothing about the article and is not listed. `items[]`: `document` (`id`, `key`, `kind`, `title`, `date`, `dossier_number`, `chamber`, `source`, `is_explanatory`), `target` (`article`, `article_version`), `target_id`, `article_version_key`, `confidence`, `scope`, `section_anchor`. `scope` is `dossier` when the memorandum explains all changes of its dossier (`semantic tk-mvt`), `article` when the edge names the section about the article in `section_anchor` (`semantic tk-mvt-articles`; the `id` of a section of the document, whose text `GET /api/documents/{key}/passages` gives). Newest first; one item per document and anchor (a version before the article, the newest version first); `limit` (1-500, default 100), `offset`, `total` counts all; empty list for an unknown article, never 404 |
| `.../cited-by` | the passages of judgments that cite the article, one row per mention (`judgment` with its `tier` and `court_kind`, `paragraph_id`, `paragraph_number`, the `leden`, `onderdelen` and `aanhef` it names, `snippet`, `confidence`), newest judgment first; `court`, `tier`, `lid` (a lid number the passage names), `limit` (max 200), `offset`, exact `total` (the passages) and `judgment_total` (the judgments they are in); 404 for an unknown article |

### Instruments and annexes

| Path | Returns |
|------|---------|
| `GET /api/instruments` | paged list of the regulations, treaties and EU acts (a publication in the Staatsblad, Staatscourant or Tractatenblad, `kind` `publicatie`, only with `kind=publicatie`); `q`, `jurisdiction` (`nl`, `eu`), `kind`, `article_count_min`, `sort` (default `title`); every item has a `display_name` |
| `GET /api/instruments/{identifier}` | one instrument: identifiers, names (`title`, `citation_title`, `short_title`, and `aliases`: every name it is cited by, `BW` and `Boek 6 BW` for Boek 6), jurisdiction, kind, dates (`date_signed`, `date_published`, `date_in_force` of the instrument itself, for a BWB regulation as enacted; `version_date_in_force`: the start of its version in force), article count (its articles, as its article list has them), `treaty_number` (a treaty: its Verdragenbank id) and `same_treaty` (the other instruments with that number: the Verdragenbank record of a BWB treaty, the BWB text of a Verdragenbank treaty; `id`, `key`, `bwb_id`, `celex`, `title`, `citation_title`, `kind`, `jurisdiction`). `identifier` is a BWB id, a CELEX number or a node key (`echr_convention`, `verdrag_012345`); 404 when unknown |
| `.../eu-links` | `implements` (EU acts the instrument implements) and `implemented_by` (publications and regulations that implement this act), `mentions` (EU acts the regulation's text names by CELEX number and does not implement) and `mentioned_by`, each with `instrument`, `relation`, `confidence`, `bases`, `source`, `meta`; `international`: treaties that articles refer to (with the treaty article) and ECHR judgments that refer to the instrument or its articles, with the edge `meta`; `*_total` fields are absolute, `limit` (max 2000) bounds each list |
| `/api/instruments/{bwb_id}/articles` | the articles in force in the order of the document (`props.position`: the Algemene bepaling of the Grondwet where it stands, an annex after the regulation; the articles of an EU act as the act prints them), each with `label`, `heading` (the title of its kop, null for most), `address`, `repealed`, `last_article_number`, each with its `breadcrumb` (the divisions it stands in: `type`, `label`, `title`); `include_stubs`, `include_repealed` (also the identities no longer in force: a number another article has now, or a current version that repeals; listed last), `text_preview_chars`, `limit` (max 2000), `offset` |
| `.../articles/at/{at_date}` | the articles of the law in force on `YYYY-MM-DD`, in the order of that day's toestand: one version per article (`valid_from <= date < valid_until`), never a lapsed one, one that left the law or the articles of a bijlage; each with `label`, `heading`, its `breadcrumb` on that day (the divisions of that day's toestand), `text_preview` (its first `text_preview_chars`, default 160, max 600) and `text` (null when `text_preview_chars` is given, unless `include_text=true`); `first_version_from`: the start of the first toestand; before it the source gives no law and the list is empty (an article's own `valid_from` can be older: 1994 for articles of the Awb, whose first toestand is of 1 April 2002); `limit` (max 2000), `offset`, `total` counts every article |
| `.../versions` | every toestand the source gives, newest first, `current` flagged |
| `.../amended-by` | amending publications (Staatsblad, Tractatenblad, ...) with edge counts per kind, articles affected, first effective date and dossiers; `limit`, `offset` |
| `.../dossiers` | dossiers through `LEGISLATED_IN` from the regulation itself (`via: instrument`) and from its amending publications (`via: amending_publication`, `publication` = newest) |
| `.../judgments` | citing judgments with the cited articles |
| `.../related-instruments` | per related instrument, inbound and outbound article-level `REFERS_TO` counts |
| `/api/annexes/{key}` | one annex with its entries (`index`, `name`, `heading`: the law the entry falls under, `parent_index`: the entry it is nested in) and `referenced_by`: the articles that name it (by label or by name) |

`IMPLEMENTS` rests on an implementation source (`bases`): `national_implementing_measure`
(EUR-Lex lists the publication, or the publication that enacted or changed the regulation, as
a national implementing measure of the act; `meta.publications`) or `considerans` (the
considerans of the regulation says it implements the act). It is not per article, so
`eu-links` has no article list for it. An act the text only names is under `mentions`
(`REFERS_TO`, `bases` empty). `international` holds what
the graph links: `REFERS_TO` edges from articles to BWB treaties (`BWBV...`) and from ECHR
judgments to instruments and to articles of the ECHR Convention. Verdragenbank treaties and
Convention articles have no link from Dutch text, so nothing is returned for them.

`articles`, `judgments`, `dossiers`, `amended-by` and `related-instruments` answer for an EU
act too; `bwb_id` in their response then holds the CELEX number as requested. `versions` and
`articles/at` are about BWB toestanden: for a CELEX number they are empty. An identifier that names nothing
gives an empty list on these routes, and 404 on the detail and on `eu-links`.

### Judgments

| Path | Returns |
|------|---------|
| `GET /api/judgments` | paged list, without the judgments known only because something cites them (stubs: no date, court or text) unless `include_stubs=true`, and without a publication of a decision that another publication replaces (`same_as`; `q` its exact ECLI finds it); `q` (a query that is the whole of an ECLI or of a case number, `18/04298`, gives the judgments with it and only those; other text is searched), `court` (ECLI code), `tier` (the `Type` of the court in the Instanties list, one of `core.courts.TIERS`: `hoge_raad`, `raad_van_state`, `centrale_raad_van_beroep`, `college_van_beroep_bedrijfsleven`, `parket` (the conclusions of the Parket bij de Hoge Raad), `gerechtshof`, `rechtbank`, `kantongerecht`, `tuchtcollege`, `andere_instantie`, `koninkrijksinstantie`, `kroon`, `buitenlandse_instantie`, `hvj_eu`, `ehrm`), `court_kind` (the kind of court within the tier, one of `core.courts.COURT_KINDS`: `ambtenarengerecht`, `raad_van_beroep`, `gerecht_in_eerste_aanleg`, …; a tier of one kind of court is its own; see [pipelines](pipelines.md#courts)), `source`, `subject` (an area of law, one of `subjects` as written: `Strafrecht`, `Bestuursrecht; Belastingrecht`), `from`, `to`, `cited_by_min`, `sort` (`date_desc`, `date_asc`, `citation_count`); each item has `tier`, `court_kind`, `subjects` (the areas of law of the source, empty when it gives none), `names` (what lawyers call it, `Haviltex`; empty for most), `decision_kind` (`arrest`, `vonnis`, `beschikking`, `uitspraak`, `conclusie`, `prejudiciële beslissing`, or null; see [pipelines](pipelines.md#rechtspraak)), `series_id` and `series_size`, `inbound_citation_count` (the judgments that cite it or a publication `SAME_AS` it) and `outbound_citation_count` (the judgments it cites); `q` also matches `names`. `facets` counts the judgments under the filters, each without its own: `tier` (`value`, `count`, most first; without the `tier` and `court_kind` filters), `court_kind` (the same, without the `court_kind` filter), `source` (`value` `rechtspraak`, `echr`, `count`, most first; without the `source` filter) and `year` (`value` the year of `date`, `count`, oldest first after null, no date; without `from` and `to`); each count reads an index, not the judgments |
| `/api/judgments/{ecli}` | the judgment with its `paragraphs` (each with a `paragraph_id` for deep links, its printed `number` and the article `citations` in it, one per occurrence with `start` and `end`; the first is the kop when the judgment has one), its `parties` (`name`, `role`, `roles` (every role the kop names, in its order: geïntimeerde and appellant in incidenteel hoger beroep), `role_stated` (a derived role is never the other side's for a public authority: the prosecution is `Officier van justitie`), `side` `first`/`second`/`other`, `alias` ("(hierna: X)", and "Partijen worden hierna A, B en C genoemd"), `representatives`; null when the judgment was normalized before parties were read, empty when the kop names none), the articles its `REFERS_TO` edges point at with their parent instrument (`articles`), and the same articles as `cited_articles` with the paragraphs that cite them, the lid or onderdeel named and a snippet. Citations are read from the stored edges; nothing is detected per request. `judgment.names` and `decision_kind` as in the list; `summary` is the Dutch inhoudsindicatie and `summary_en` an English one: an English translation (its own ECLI, `translation_of` the ECLI of the Dutch judgment) has the Dutch `summary` of that judgment, and that judgment the English `summary_en` (see [data-model](data-model.md#judgment)). `judgment.series_id` and `series_size` name the series of parallel cases it is one of (the same court, day and text), `series` the other judgments of it. `cited_judgments` are the judgments its text cites (`REFERS_TO`), newest first; `judgment.same_as` is, for a replaced publication, the ECLI of the one kept, and `same_as` the other publications of the decision (`SAME_AS`, either way) |

The judgments of one case are neighbours in `/api/nodes/judgments/{key}`: `APPEAL_OF` (appeal →
the judgment appealed; `meta.basis` `formal_relation` or `appeal_text`), `CONTINUES` (a judgment
→ an earlier one of the same court in the same case), `REFERRED_BY` (a decision after referral →
the Hoge Raad ruling that sent the case back), `ADVISES_ON` (the conclusion of an
advocate-general → its judgment, never the other way; `formal_relation` or `case_number`) and
`ANSWERS` (a preliminary ruling → the decision that asked its questions; `formal_relation` or
`referral_text`). A judgment has the inbound bucket, its conclusion or its referring decision
the outbound one. Two judgments tied so are not also under `REFERS_TO`, and such a link is not
in `inbound_citation_count`. `/api/judgments/{ecli}` has `judgment.unresolved_appeal_targets`:
the decisions an appeal names in its text that are not loaded (`court`, `date`,
`case_number`), empty for most.

### Parliament

Every dossier in a list or a detail has `number` (its label), `suffix` (`XV` of `37020-XV`, null
without one), `same_number_count` (the other dossiers of its number: 24 for each dossier of a
budget of 25), `title`, `kind` (what the dossier is, as the Kamer names it: the `Zaak.Soort`
of its own zaak, `Wetgeving`, `Initiatiefwetgeving`, `Begroting`, `Verdrag`, `Initiatiefnota` or
`PKB/Structuurvisie`; without one, `Wetgeving` or `Initiatiefwetgeving` from a `Voorstel van
wet` among its papers; null for a dossier of letters and motions), `kind_basis` (`case`: its
zaak; `document`: its voorstel van wet), `phases` (of a `Wetgeving`, `Initiatiefwetgeving` or
`Begroting`, null for another kind: every phase of the curated list `phases` in its order
(each with `chamber` `TK`: the bar is that of the Tweede Kamer),
`Voorstel van wet`, `Memorie van toelichting`, `Advies Raad van State`, `Verslag`, `Nota n.a.v.
het verslag`, `Nota van wijziging / Amendement`, `Stemmingen`, `Eindtekst`, each `{name, done,
date}`: done when a paper of the dossier, an activity about it that took place or a decision on
its own zaak has a value of the Kamer the list names for it, `date` the first date of those),
`current_phase` (the furthest done phase in the order of the list, not the one with the latest
date: the Kamer may date a paper by the day it was received, 36937 its Nota n.a.v. het verslag
four days after the bill passed; null for none), `closed`, `outcome`, `tk_decision` (the last decision of the Kamer on its bill: `kind`
its `BesluitSoort`, `Stemmen - aangenomen`, `Stemmen - zonder stemming aannemen` for a
hamerstuk, `Stemmen - verworpen`, `Stemmen - uitstellen`, …; `text`, `date`; null for none),
`ek_outcome` (the outcome of the bill in the Eerste Kamer, as eerstekamer.nl gives it:
`outcome` `Aangenomen`/`Verworpen`, `date`, `method` (`Hamerstuk`, `Stemming bij zitten en
opstaan, aangenomen`, …; null for a rejection before June 2015), `source_url` (the report of the
vote, or the list of rejected bills), `retrieved_on`, and `attribution` (`EK_ATTRIBUTION`: the
source to name with it); null when the Eerste Kamer has not decided; its outcome closes the
dossier: `aangenomen` or `verworpen` on the day of the vote, a Staatsblad publication dating an
adopted law),
`opened_on` (the day it opened, as the Kamer dates its papers: of nr. 1 of its own numbering,
the paper whose own dossier (`Document.Kamerstukdossier`) it is; else of its Koninklijke
boodschap; else of its first paper or activity) with `opened_on_basis` (`first_paper`,
`royal_message`, `earliest_record`), and `closed_on`. A
`subject` filter takes a number (`37035`: every dossier of that
number), a dossier (`37035-XXII`, `37035 xxii`) or words of the title.

`tk_url` of a Tweede Kamer document or activity, wherever it appears (timeline, document lists and
detail, node responses), is its page on tweedekamer.nl, made from the number the site knows: the
document number (`kamerstukken/detail?id=2026D44984&did=2026D44984`) or the activity number
(`debat_en_vergadering/plenaire_vergaderingen/details/activiteit?id=…` for a plenary kind,
`debat_en_vergadering/commissievergaderingen/details?id=…` for any other). It is null when the node
has no such number, as an Eerste Kamer paper, whose page is its `url`.

The Eerste Kamer (`?chamber=EK` on the lists of factions, committees and members and on the
seats) is what eerstekamer.nl shows on the day it was read: the site gives the composition of
today, and no start or end of a membership as data. So a period is what was observed:
`observed_from` is the day of the first snapshot that showed it, `observed_until` the day of
the first that no longer did (null while it is shown); neither is the day it began or ended,
and nothing before the first snapshot is known. A member's `ek` holds `name` (as the Kamer
writes it, `mr. B.O. Dittrich`), `faction` (key) and `abbreviation`, `seniority_days`
(`Anciënniteit`: the days served, earlier terms included; no start date), `residence`,
`observed_from`, `observed_until` and `source`. Everything taken over from eerstekamer.nl
carries `source` (`url`, `retrieved_on`, `composition_date`: the day of the composition shown,
`data_since`: the day of the first snapshot, before which nothing is known, and `attribution`:
`EK_ATTRIBUTION`, to name with it).
A member of the Eerste Kamer who was a member of the Tweede Kamer is one member: the one born
that day whose surname ends their name, when exactly one is; else a member of their own,
`ek_<slug>`.

The end of a cabinet, of a phase of a cabinet and of a post in it (`to_date`, in
`/api/cabinets`, in a cabinet's `phases` and seats, and in a member's `government_functions`)
is the day of the change as Rijksoverheid gives it: the day the next cabinet, phase or holder
takes office. A period runs from `from_date` up to, not including, `to_date` (half-open, as the
validity of an article version); `to_date` is the `from_date` of what follows (in every change
of cabinet since 1945, and for a post whenever a successor took over the same day). `to_date` is
null while it lasts.

| Path | Returns |
|------|---------|
| `GET /api/dossiers` | every dossier, open and closed; `status` (`open`, `closed`, `all`, default `all`), `outcome`, `kind` (comma-separated, of those above), `number` (the start of the label: `36264` gives that dossier and its chapters, `37020-` the chapters of 37020), `committee` (slug), `subject` (a number, a dossier such as `37035-XXII`, or words of the title, which holds the short title: `Verzamelwet gegevensbescherming`), `phase` (the current one), `has_phase` (all listed phases done), `ministry`, `initiative`, `opened_from`, `opened_to` (dates), `sort` (`number`: in the order of the Kamer, no suffix, numeric suffixes by value, budget chapters by value with their letter, then the rest (`props.order`); `opened_on` and `closed_on` newest first; `title`; ties by key; default `number` with a `number` filter, else `opened_on`), `limit`, `offset`; `total` counts every match. `facets`: per `status`, `outcome`, `kind`, `phase` and `ministry` a list of `{value, count}` under the current filters, each dimension counted without its own filter, the largest first (`value` null counts the dossiers without one). Every dossier summary in the API carries `short_title` (a budget by its chapter and year, `Begroting Defensie 2027`, a change of it also by its nota, `Suppletoire begroting gemeentefonds 2026 (Miljoenennota)`, a slotwet as `Slotwet Defensie 2025`; else the parentheses that end the title), and `ministry` (of the bewindspersoon who signed its earliest signed document first), `initiative` (a Kamerlid signed first) and `cabinet` (in office then), null when unknown |
| `/api/dossiers/{number}` | header (with `closed`, `outcome` `aangenomen`/`verworpen` or null, `tk_decision`, `ek_outcome`, `opened_on`, `closed_on`, `kind`, `phases`, `current_phase`), counts of documents, activities, decisions, commitments, and the dossier hub: `instruments` (`id`, `key`, `bwb_id`, `celex`, `display_name`, `jurisdiction`, `relation` `legislated_in`/`amends`/`introduces`/`repeals` and `status` `canoniek`/`voorgesteld` of its first link, and `links`: every `relation` and `status` the dossier has with it, enacted first; one item per instrument), `laws_named` (the laws its title names, `Wetboek van Strafvordering`, each with `loaded`, `key` and `bwb_id`: whether the graph holds it, found by its citation title), `committees` (leading an activity about the dossier, `role` `lead`), `documents_by_kind` (counts per document `kind`), `senate` (`document_count`, `first_date` of the Eerste Kamer papers), and `relations`: the dossiers it `revises` (a supplementary budget or slotwet: the budget of its chapter and year; `rule` `begrotingswijziging`/`slotwet`), `accompanies` (a budget change: the Voorjaarsnota, Najaarsnota or Miljoenennota its title names, `nota`) or is `related_to` (the Kamer relates a case of the one to a case of the other; `cases` counts the pairs, `case_kinds` names them, `Brief regering → Motie`) or is the `second_reading_of` (a change in the Grondwet in its second reading and its first reading, whose memorandum explains it: 35785 → 35418, 35419), each with `direction` (`outgoing`: this dossier revises, accompanies, relates; `incoming`: the other one does) and the other `dossier` as a summary; ordered by relation, outgoing first, then by number |
| `.../timeline` | documents, activities, decisions and commitments; `order` (`desc`, `asc`), `kind` (comma-separated), `include_planned` (default true; false leaves out activities still `Gepland`), `limit`. Each entry has `after_closure` (dated after the dossier's `closed_on`: a follow-up letter or meeting, kept), `planned` (an activity with status `Gepland`), `node_type` and a `body` typed by it: a document (`kind`, `title`, `sequence`, `dossier_number` (the dossier `sequence` is a number of: a paper of a case of this dossier may be numbered in another; null for no Kamerstuk), `session_year`, `tk_url`, `url`, `chamber`, `source`, `is_explanatory`; never its text), an activity (`kind`, `agenda_title` (its subject), `number`, `status` as the source writes it: `Gepland`, also for a date that has passed or lies after the dossier closed, `Uitgevoerd`, `Geannuleerd`, `Verplaatst`, `Vervallen`; the entry also has `committee` `{key, slug, name}`, null for plenary), a decision (`subject`, `chamber` (`TK`, `EK`), `result` and `method` (of the Eerste Kamer, as it writes them), `passed`, `decision_kind` (its `BesluitSoort`), `vote_kind`, `tally`, `voters`, `external_id`, `primary_case_kind` (`Wetgeving` on the vote on the bill itself, `Amendement`, `Motie`, …), and the decided `document` with `dictum_excerpt` and `signatories`, each with `role`, `source_role`, `function` and `capacity`) or a commitment (`text`, `minister_name`, `minister_role`, `status`, `expected_resolution`) |
| `.../documents` | documents linked directly or through a case, newest first, with `total`; each has `sequence` and `dossier_number` as in the timeline; like every document in the API each has `chamber` (`TK`, `EK`, null for Staatsblad and Staatscourant), `source` and `is_explanatory` |
| `.../mutations` | the subgraph of `voorgesteld` edges, in graph shape |
| `GET /api/ministries` | every ministry name of `data/ministries.json` in protocol order: `key`, `name`, `abbreviation`, `tooi` (the TOOI code), `successor` and `until` of its last period (the name that followed, and the last day it had its name), and `periods` (`from_date`, `until`, `successor`, `basis`: the Staatscourant decree the end rests on, `source`: `tooi` or `rijksoverheid`, `successor_source`: `curated` for a succession before 2010 that no source gives) |
| `GET /api/cabinets` | every Dutch cabinet since 1945, newest first, from Rijksoverheid (none before: no official source describes them). `key`, `name`, `from_date` (the beëdiging), `to_date` (null for the cabinet in office), `previous`, `prime_minister` (`key`, `name`), `parties` (`short`, `faction`: of the bewindspersonen sworn in on its first day), `factions`, `demissionary_from` (the start of its first `demissionair` phase), `phases` (`kind`: `formatie`, `in_functie`, `demissionair`, `dubbel_demissionair`, `missionair`, or null for the stretch after elections when the source gives no day of resignation; `from_date`, `to_date`, `label` in the source's words, `source`; in order, each ending where the next begins), `source` (`name`, `url`, `read_on`), and the counts `members` (who held a post in it), `bills` (dossiers of track `wetsvoorstel` a bewindspersoon brought in while it was in office) and `commitments` (made while it was in office) |
| `GET /api/cabinets/{key}` | the cabinet as in the list, with `ministries`: per ministry (protocol order; Algemene Zaken with the minister-president first, a group with `ministry` null last for a post no official source places under a ministry, such as the viceminister-president; see [pipelines](pipelines.md#rijksoverheid)) its `seats` in protocol order (minister-president, viceminister-president, minister, minister without portfolio, staatssecretaris): `seat` (`ienw/minister`, `-/staatssecretaris/rechtsbescherming` where the function names no ministry; `#2` for a second seat the source names no portfolio of), `post`, `portfolio`, `function`, and its `posts` in order of start: `member` (`key`, `name`: the name they go by), `post`, `function`, `also_named`, `seat`, `portfolio`, `from_date`, `to_date`, `from_date_source` and `to_date_source` (what the source gives; null when nothing), `corrected`, `acting` (a stand-in) with `acting_reason` (`source`: the page says so, its words in `acting_basis`; `held_other_seat`: the holder held `acting_other_seat` (`seat`, `function`) throughout), `ministry_source` (`page`, `tk_signatures`, `tk_commitments`, `staatscourant`) or `ministry_missing` (`no_source`, `ambiguous`), `party` (`short`, `faction`), `overlaps_with` (member keys that held the seat at the same time: a conflict in the source), `absent`, `source`, and the person's counts within the cabinet's period: `dossiers` (with a paper they signed as bewindspersoon), `bills` (of those, track `wetsvoorstel`), `open_commitments`. A successor is the next post of a seat, a stand-in a post with `acting`. A person with two posts is listed under each. 404 for an unknown key. `/api/nodes/cabinets/{key}` gives the node and its `SERVED_IN` neighbours |
| `GET /api/commitments` | commitments (toezeggingen), paged, `total` absolute; `status` (the `Toezegging.Status` the Kamer gives it: `Openstaand`, `Afgedaan`, `Deels Afgedaan`, `Nagekomen`, `Niet nagekomen`, `Vervallen`), `member` (key), `cabinet` (key), `ministry`, `dossier` (a number or label), `due_before` (date), `overdue` (`Openstaand` with `expected_resolution` passed), `q` (words of the text), `sort` (`date`: newest made first; `expected_resolution`: soonest due first, those without one last), `limit`, `offset`. Each item: `key`, `number` (how the Kamer cites it, `TZ202603-130`; `/api/resolve` finds it), `text`, `status`, `date` (made on), `expected_resolution` (null when the Kamer names none), `minister_name` as the source writes it, `member` (`key`, `name`, `function`: the role it was made in; null when no member fits), `post`, `ministry`, `cabinet`, `dossiers` (`key`, `number`, `title`), `activity` (`key`, `date`, `number`) |
| `GET /api/commitments/{key}` | one commitment as in the list; 404 when unknown |
| `GET /api/decisions`, `/{key}`, `/{key}/document` | decisions with every vote cast — per member on a roll-call, per faction otherwise; the decided motion, amendment or bill with text. The list filters on `kind` (comma-separated: the `Zaak.Soort` of the case decided as the Kamer writes it, `Motie`, `Amendement`, `Wetgeving`, `Begroting`, …; see [data model](data-model.md)), `passed`, `party` (the decisions its faction voted on; with `vote` `voor`/`tegen` the ones it voted that way on; a roll-call has no faction vote), `chamber` `TK`/`EK` (the votes of the Eerste Kamer: a decision per vote of its list, with `result` `Aangenomen`/`Verworpen` as it shows it, `method` as its report names it, `bill_decision` (whether it is the vote that decided the bill: the list names a vote on a motion by its bill too), `kind` (of the vote that decided the bill: the kind of its dossier, `Wetgeving`, …; null for a vote on a motion, which the list names no kind of), and in the detail `factions_for`, `factions_against`, `factions_noted`, `bill_url`, `source_url`, `retrieved_on`; no votes per faction, so no `tally`), `dossier` number, `from` and `to` (the date of the vote, YYYY-MM-DD) and `q` (a part of the subject, in any case). Each item has `kind` and `decision_kind` (the `BesluitSoort`: `Stemmen - aangenomen`, `Stemmen - zonder stemming aannemen` for a hamerstuk without votes, `Stemmen - uitstellen`, whose `passed` is null); `total` is the matches, independent of `limit`. `facets` counts the decisions under the filters: `kind` (`value`, `count`, most first; without the `kind` filter), `passed` (`value` `true`/`false`/null, `count`; without the `passed` filter) and `days` (`date`, `count`, how many `passed`, oldest first; under every filter). The detail has `primary_case_kind`; list and detail have `dossier_numbers` and `chamber` |
| `GET /api/committees`, `/{slug}` | committees, each with `slug` (its own: of committees that share an abbreviation the one sitting now, else the one that ended last, has it bare, the others with the year they started, `ez-2010`), `kind` (`vast`, `algemeen`, `tijdelijk`, `enquete`, `delegatie`, `overig`), `started_on`, `ended_on` (null while it sits) and `active_dossier_count` (the open dossiers it leads an activity about, the same in list and detail; 0 once it ended); detail lists current members (`current_only=true`, the default) and a page of the dossiers it leads, newest first (`status` `open`/`closed`, `limit`, `offset`; `dossier_total` counts the matches). `?chamber=EK` lists the committees of the Eerste Kamer instead (key `ek_<slug>`, `slug` `ek-<slug>`, `chamber` `EK`; see below), whose detail lists its members with `role` (`voorzitter`, `ondervoorzitter`, as its page gives it) and `observed_from`/`observed_until` |
| `/api/committees/{slug}/activities` | the activities the committee leads, newest first, each with `date`, `kind`, `agenda_title`, `status`, `dossier_numbers`; `limit`, `offset`, `total`. The plenary is no committee: a plenary activity is led by none |
| `GET /api/members/{key}` | the member, with `name` (the name they go by, `Ard van der Steur`: `Persoon.Roepnaam` with the surname; for a TK person without a name, as Rijksoverheid gives it; also in the list), `full_name` (`Gerard Adriaan van der Steur`), `birth_date`, `government_name` (the name as Rijksoverheid writes it) and `government_functions`: every post they held in a cabinet since 1945 (`function` as Rijksoverheid names it, `cabinet`, `cabinet_key`, the normalised `post` and `ministry`, `seat`, `acting`, `party` (`short`, `faction`), `from_date`, `to_date`, oldest first; empty for a member who held none). A minister who never sat in parliament has the name Rijksoverheid gives; a bewindspersoon the Tweede Kamer has no person for is a member of their own (`rijksoverheid_<initials>_<surname>`) |
| `GET /api/members`, `/{key}`, `/{key}/votes`, `/{key}/dossiers`, `/{key}/touched-instruments` | members, each with its `government_functions` (filter `party`, `active`, `q`; ministers only with `include_all`, `capacity=bewindspersoon` (everyone who held a post in a cabinet) or `cabinet` (a cabinet key: who held a post in it); a record without a name is never listed); a member's votes, a faction vote counted only for the period they belonged to it; the dossiers the member authored documents in (`AUTHORED`), each a dossier summary plus `roles` (the source's role names), `functions` and `capacities` (what the member signed as there: `kamerlid`, `bewindspersoon`, `overig`, see [data-model](data-model.md#parliament)) and `document_count`, paged with `total`; in `/api/nodes/members/{key}` every `AUTHORED` edge carries `meta.role`, `meta.function` and `meta.capacity` of that signature; laws the member proposed changes to. `?chamber=EK` lists the members of the Eerste Kamer (with `party` their faction's abbreviation, `active` those the last snapshot shows); a member of the Eerste Kamer has `ek` (below), in the list and the detail |
| `GET /api/factions`, `/{key}`, `/{key}/dossiers`, `/{key}/touched-instruments` | factions with member counts; the same two aggregates per faction (its dossiers are those its members signed documents in while they belonged to it). `?chamber=EK` lists the factions of the Eerste Kamer (key `ek_<slug>`, `chamber` `EK`, `seats`, `board`: `{function, name, member, since}` as its page gives it, `member_count` the members the last snapshot shows, `observed_from`, `observed_until`, `source`); `/{key}/votes` of a faction of the Eerste Kamer: the votes of its list that name it, newest first (`from`, `to`, `limit`, `offset`), each with `choice` as the list names it (`voor`, `tegen`, `aantekening gevraagd`), `result`, `method`, `bill_decision`, `date`, `subject`, `dossier_numbers`, and `counts` per choice and `total` over every such vote; 422 for a faction of the Tweede Kamer (whose votes per faction are `/api/decisions?party=`) |
| `GET /api/parliament/seats` | seated factions with seat counts in the order they sit in the plenary hall, from the chair's left (`order`), after the seating plan of the Tweede Kamer (`seating_plan`: `title`, `dated`, `url`, `page`; kept with `lawgraph curated set seating`, updated at every Presidium decision on the seating; a faction the plan does not place sits at the right end); `?date=YYYY-MM-DD` gives the seats the members held that day (complete from the Kamer installed on 30 November 2006), in the order of today's plan. `?chamber=EK`: the seats of the Eerste Kamer (`total_seats` 75) as eerstekamer.nl shows them on the day it was last read (`as_of`, `source`), in the order of their size; no `seating_plan` and no `date` |
| `GET /api/parties/colors` | `colors`: party to hex colour, by every name and alias (match without regard to case); `aliases`: another name of a party (`GL-PvdA`, `CU`) to its name in `colors`. From the parties' own house styles, kept by hand (`lawgraph curated set party-colors`) |
| `GET /api/documents/{key}` | one document with its `title` (of a motie, amendement, letter or report its own subject, not its dossier's), `tk_url` (its page), `file_url` (the original Word or PDF file of a Tweede Kamer document, from the Gegevensmagazijn), its extracted text (null when `normalize tk-content` has not reached it), `submitters` (of a motie or amendement, the indiener first: `name`, `faction`, `member_key`, `role` `indiener` or `medeindiener`; empty for any other paper), its `sections` (the headings of the paper: `id`, `heading`, `level`, `parent`, `kind`, `number`, `number_scheme`, `article_refs`, `law`, `char_start`, `char_end`; offsets into `text`, empty without text), `dossier_numbers` (the dossiers it is `PART_OF`, in either chamber), `case_kinds` (the `Zaak.Soort` of its cases) and `explains` (the articles and instruments it `EXPLAINS`: `id`, `key`, `collection`, `bwb_id`, `article_number`; an article version resolves to its article, an instrument has no `article_number`) |
| `GET /api/documents/{key}/passages?bwb_id=&article=` | the sections of a memorandum that explain an article (or one of its versions), in document order: `section_id`, `heading`, `level`, `char_start`, `char_end`, `text`, `confidence` (uncalibrated), `match_type`; with `total`; empty list for an article without passages or a document without text, 404 for an unknown document |

### Feed

What was promised and proposed, as one stream of events, newest first. An event is a node
of the graph with a date; nothing is stored for the feed. The `kind` of a paper is its
`Document.Soort` up to ` (` (`Motie (gewijzigd/nader)` is a `Motie`), its `subkind` the whole
`Soort`.

| `kind` | Event | Node, date |
|--------|-------|------------|
| `toezegging` | a commitment made (its current `status`; the source gives no date of a change) | commitment, `made_on` |
| `Voorstel van wet` | a bill submitted, also of an initiative; its submitters are who sign it, or, where the source leaves the voorstel unsigned, the first memorie van toelichting of its dossier | Tweede Kamer document, `date` |
| `Nota van wijziging` | a note of change, also of an initiative | Tweede Kamer document, `date` |
| `Amendement` | an amendment, also a changed one | Tweede Kamer document, `date` |
| `Motie` | a motion, also a changed one | Tweede Kamer document, `date` |
| `Brief regering` | a letter of the government | Tweede Kamer document, `date` |
| `stemming` | a vote with an outcome (`passed` true or false) | decision, `date` |
| `publicatie` | a publication in the Staatsblad, Staatscourant or Tractatenblad | instrument of kind `publicatie`, `date_published` |
| `inwerkingtreding` | a new version (toestand) of a law in force | instrument version, `valid_from`: the start of the toestand as the BWB lists it (`retrieve bwb-history`). A date ahead appears once the BWB holds that toestand; a commencement a besluit names but the BWB does not yet list is not in the feed |

| Path | Returns |
|------|---------|
| `GET /api/feed` | `items`, `next_cursor`, `total`, `facets` and `data_as_of` (as in `/api/stats`). Filters: `kind` (comma-separated), `since`, `until` (YYYY-MM-DD, inclusive), `cabinet` (a key: the events from its beëdiging to that of the next cabinet), `ministry`, `dossier` (the start of a dossier label: `36600` holds `36600-VII`, `37020-` the chapters), `member` (a member key: the papers they signed, the votes on them, the commitments they made), `faction` (a faction key: the papers its Kamerleden signed for it and the votes on them), `q` (words of the title or of the title of the event's dossier, any case), `chamber` (`EK`: the votes of the Eerste Kamer, only the one that decided each bill; `TK`: the papers, votes and commitments of the Tweede Kamer; publications and commencements are of neither); `limit` (1-200, default 50), `cursor` (the `next_cursor` of the page before; 422 for a token the API did not hand out). Order: `date`, newest first; within a day by kind, in the order `Voorstel van wet`, `stemming`, `toezegging`, `inwerkingtreding`, `publicatie`, `Nota van wijziging`, `Amendement`, `Motie`, `Brief regering`; within a kind by `id`. The cursor holds the date, kind and id of the last event of its page, and a page starts after it, so pages neither repeat nor skip an event. `facets` (default true) counts per `kind`, `ministry`, `faction`, `cabinet` and `chamber` (`TK`, `EK`, null for a publication or a commencement) (`{value, count}`, the largest first, `value` null for none) the events under the other filters, and `total` under all of them, whatever the cursor; `facets=false` gives null for both and reads one page only, the choice for the pages after the first |
| `GET /api/feed/summary` | a few days in one small answer: `until` (default today), `days` (1-31, default 3), the filters of `/api/feed` but `since` and `until`, `margin` (default 10), `few` (default 2), `limit` (1-500, default 100). `days`: every day from `until` back, newest first, each with `total`, `kinds` (`{value, count}`), `dossiers` (per kind, in the order of a day, and first dossier of an event: `kind`, `number`, `key`, `title`, `short_title`, `short_title_basis`, `count`, most first within a kind) and `votes` (`chamber`, `subkind`, `outcome`, `count`); `items`: the events a timeline shows one by one, as feed items in the order of the feed: bills submitted, votes on a bill (`subkind` `Wetgeving`, `Initiatiefwetgeving` or `Begroting`, a hamerstuk too, and every vote of the Eerste Kamer), votes whose seats for and against differ by at most `margin`, every vote of a day with at most `few` votes on anything but a bill, commitments and commencements; `items_truncated` when more than `limit` qualified; `data_as_of` as in `/api/feed`. One query over the window |
| `GET /api/feed.atom` | the same page under the same parameters (without `facets`) as an Atom 1.0 feed (`application/atom+xml`), named after its filters (`Concordans`, `Concordans: moties`, `Concordans: dossier 36600`), with an `alternate` link to the same view on Concordans (`<LAWGRAPH_SITE_URL>/actueel?soort=Motie`: `soort`, `van`, `tot`, `kabinet`, `ministerie`, `dossier`, `persoon`, `fractie`, `q`) and a `next` link with the cursor; an entry per event (`id` `tag:lawgraph,2026:<id>`, `title`, `updated` the date, an `alternate` link to the event on Concordans (`/explore?focus=<id>`) and a `related` one to its `official_url` or `tk_url`, `category` its kind, an `author` per person, `summary` its summary and dossier) |

Each item: `id` (`collection/key` of its node), `kind`, `date` (no time of day; the source
gives none), `title` (a bill the title of its dossier, a commitment its first words, another
paper or a vote its subject, a publication its citation title, a version the title of its
law), `summary` (the text of a commitment, the
decision of a vote, `Aangenomen.`; else null), `subkind` (the whole `Document.Soort`,
`Motie (gewijzigd/nader)`; for a vote what was voted on, the `Zaak.Soort`: `Motie`,
`Amendement`, `Wetgeving`, …, null when the Kamer names no one Soort), `dossier` short titles: `short_title` the name the dossier goes by and `short_title_basis` where it comes from: `title` (of a budget its chapter and year, else the parentheses that end the title), else official data of its bill: `citation` (the citation title the bill gives itself, "Deze wet wordt aangehaald als: …"), `case` (the citation title the Kamer gives the bill's case), `amended_law` (the citation title of the one Dutch law the bill changes: then it names that law, not the bill); both null when there is none, `headline` (the parts a headline is made of:
`surname` of the first `indiener`, `subject` the part of the title after its first ` over `,
`short_title` of its dossier; each null without), `node` (`collection`, `key`), `dossier` (the first:
`key`, `number`, `title`, `short_title`; null without), `persons` (`key` a member key, `name`
as the member routes give it, the name they go by and the surname, else as the paper writes
it, `surname` with its prefix (`van der Plas`), `function` what they signed as, as the source
writes it (`minister van Financiën`, `Tweede Kamerlid`; of a commitment the role it was made
in), `role` `indiener` (the first signatory), `medeindiener` or `bewindspersoon` (a
bewindspersoon who signs a bill or a note of change is its `indiener` or `medeindiener`),
`faction` (`key`, `short`) of a Kamerlid; of a vote the signatories of the paper it decided;
the griffier and other signatures that are neither are left out), `ministry` (of a commitment its own, else
the `ministry` of its first dossier: who brought the dossier in), `cabinet` (in office on
`date`), `official_url` (a publication, a version of a law), `tk_url` (a paper), and by kind:
`vote` (`chamber` `TK`/`EK`, `passed`, `outcome` `aangenomen`/`verworpen`, `vote_kind` `member`/`faction`, `tally`
as the source writes it), `commitment` (`status`, `expected_resolution`), `publication`
(`series` `stb`/`stcrt`/`trb`, `year`, `number`, `instruments`: the laws it amends,
introduces or repeals, up to ten, `key`, `title`, `official_url`), `commencement`
(`instrument`, `article_count` of the law, `changed_articles`: the articles with a version
that begins that day).

### Nodes, search, resolve

| Path | Returns |
|------|---------|
| `/api/nodes/{collection}/{key}` | a node (any node collection) with its neighbours in buckets of one relation, direction and neighbour collection. Every neighbour carries its edge: `edge_id` (the edge `_key`), `status`, `confidence`, `meta`. A bucket has `type`, `total` (its edges), `next_offset` (null on the last page) and `items`; `limit` (default 30, max 200) and `offset` page inside every bucket. Bucket and page order are the same on every request |
| `.../neighborhood` | nodes and edges within `depth` (1-4) hops, capped by `cap`; the filters below shape the traversal |
| `/api/nodes/in-flux`, `/api/nodes/heat` | node id to count of open proposed mutations; node id to incoming edges created in the last `months` (default 6), `min_count`. Both answer a plain map (`{"articles/bwbr0001854_287": 3}`), not validated through a response model |
| `GET /api/search?q=` | text search over `types` (`articles`, `committees`, `documents`, `dossiers`, `factions`, `instruments`, `judgments`, `members`; all by default), `kind`, `limit`. A citation in `q` (`art. 6:162 BW`, `artikel 287 Sr`, `Sr 287`, a full ECLI) puts its article or judgment first, and so does the whole name of a judgment (`Urgenda`, `Lindenbaum/Cohen`: one of its `names`, any case). Every hit has a `score`, its rank tier for `q`: an identifier of the hit (1), its whole name (0.75), the start of its name (0.5), every word of `q` in its name (0.25), a match on words only (0.1); a type lists its hits best first, ties in database order. The names of a hit are its `display_name`, citation title, the `heading` of an article and the `aliases` of an instrument (`BW`, `Boek 6 BW`, `6 BW`: 0.75, before the words); `q` inside the title of a division an article stands in counts as part of its name (0.25). Scores compare across types: a heading or alias that is `q` (0.75) outranks a judgment that only holds its words (0.1). Within a type the database orders by BM25 before the `limit`, with a word in a heading (x4), a division title (x1.5), a display name (x2), an alias or short title (x3) weighing more than one in a text; an instrument whose alias or short title is the whole of `q` is always fetched. `extra` of an article carries `instrument_title` (its law), `heading` and `division_titles`, of an instrument `short_title` and `aliases`, of a judgment `ecli`, `appno` and `names`, of a document `dossier_number`, of a dossier `number`, `kind`, `current_phase`, `closed` and `outcome`. A document hit has in `extra` its `kind`, `external_id`, `dossier_number` and `sequence` (its number in the dossier: nr. 12) |
| `GET /api/resolve?q=` | the one node a citation, identifier or law name names (an article also without the word artikel, law first or number first: `Sr 287`, `6:162 BW`, `287 Sr`): `kind` (`article`, `instrument`, `judgment`, `dossier`, `document`, `commitment`, or `none`), `match` (`id`, `key`, `collection`, `kind`, `display_name`, `confidence`), `confidence`, `alternatives` (up to five, same shape, best first) and `qualifier` (`derde lid` of `artikel 287, derde lid, Sr`). Nothing that fits is 200 with `kind` `none` and `match` null, so the caller searches the words instead; only an empty or over-long `q` is 422 |

### Resolve notations

`/api/resolve` reads `q` as, in this order:

| Notation | Examples | Target | Confidence |
|----------|----------|--------|------------|
| ECLI, BWB id, CELEX id | `ECLI:NL:HR:2023:123`, `BWBR0001854`, `32016R0679` | the judgment or instrument with that key | 1 |
| Number of a toezegging | `TZ202603-130` | the commitment with that `number` | 1 |
| Article of a named law: keyword and number, or law and number | `art. 6:162 BW`, `artikel 287 Sr`, `artikel 3.26 van de Wet ruimtelijke ordening`, `Sr 287`, `Awb 3:4` | the article, by key; several articles (`artikelen 36e en 36f Sr`) give the first as match, the rest as alternatives | 0.95 |
| Kamerstuk | `36327`, `Kamerstuk 36327`, `36 327`, `29684-I` | the dossier with that number and suffix; other suffixes of the number are alternatives (0.5) | 0.95 |
| Paper of a Kamerstuk | `36327-3`, `Kamerstukken II 2020/21, 36327, nr. 3`, `kst-36327-3` | the document with that ondernummer in the dossier; the dossier (0.6) when the graph lacks the paper | 0.95 |
| Law name or abbreviation | `Wetboek van Strafvordering`, `Grondwet`, `Sr` | the instrument | 0.9; the start of a name 0.6, part of a name 0.4 |
| Heading of an article without a number, and its law | `Algemene bepaling Grondwet` | the article | 0.95 |
| Article without a law | `artikel 6`, `art. 6:162` | the most cited article with that number; the others are alternatives | 0.5 for one law, 0.3 for several |

The article number is read as the graph stores it: a law that numbers with a colon keeps it
(`3:4` of the Awb), while every book of the Burgerlijk Wetboek is a regulation of its own and
the book before the colon picks it (`BW6`); the article is then `162`, so `art. 6:162 BW` is
never article `6`. A law is known by its `short_title`, its
citation title or its title; a name two laws share names no article but lists both laws as
alternatives, and several equally good nodes cap the confidence at 0.5. A bare number needs five
digits (`36327`) unless it follows `Kamerstuk` or `dossier`.

### Semantic relationships

| Method | Path | Notes |
|--------|------|-------|
| GET | `/api/relationships/types` | the seven semantic types |
| GET | `/api/relationships/search` | classified article relations; `type` (the types to keep) and `exclude_type` (the types to leave out), each comma-separated (`exclude_type=cross_reference` gives every other kind), `law` (`bwb_id` of the source article), `limit`, `offset` |

### Neighbour filters

`/api/nodes/{collection}/{key}` and `.../neighborhood` take the same filters:
`relations` and `node_types` (comma-separated relation names and `NodeType` values),
`direction` (`outbound`, `inbound`) and `status` (`canoniek`, `voorgesteld`). A name that does
not exist is 422. On the node route they narrow the edges, so totals count what
remains. On `.../neighborhood` they shape the walk: it follows only edges of those relations
and status, only in that direction (at every hop), and only through nodes of those types (the
focal node is always kept); the edges returned between the kept nodes are those of the
relations and status.

## Response conventions

- Every DTO forbids unknown fields (`extra="forbid"`).
- Node references use `id` (`collection/key`) and `key`; edges use `from` and `to`.
- List responses carry `items` and `total`, the absolute number of matches independent of
  `limit`. Some carry a domain name instead of `items` (`entries` for timelines, `versions`,
  `votes`, `relationships`). The neighbours of a node are grouped in `buckets`, each with its
  own `items`, `total` and `next_offset`.
- Errors: 400 a node collection the API does not serve or an unknown search type, 404
  unknown resource, 422 invalid parameter, 429 rate limited, 503 from `/api/health` when the
  database is unreachable.
- Responses of the route handlers carry an `X-Request-ID` header.

## Layout

| Path | Contents |
|------|----------|
| `api/app.py` | app, middleware, router registration, `lawgraph-api` entry point |
| `api/routes/` | one module per domain (`articles`, `instruments`, `judgments`, `dossiers`, `committees` (also `members` and `factions`), `government` (`ministries`, `cabinets` and `commitments`), `decisions`, `documents`, `nodes`, `resolve`, `search`, `stats`, `relationships`, `annexes`, `parliament` (also `parties`), `feed`) |
| `api/schemas/` | Pydantic DTOs, one module per route module; shared ones in `common.py` |
| `api/params.py` | parsing of query parameters shared by routes (comma-separated choices, 422 on a value that does not exist) |
| `api/dependencies.py` | `get_store()`: one shared `ArangoStore` |
| `core/cache.py` | `TTLCache`: in-process LRU with TTL (`LAWGRAPH_CACHE_TTL` 60 s, `LAWGRAPH_CACHE_MAXSIZE` 512) used by several routes and the search |
| `db/queries/` | the queries of the routes, one module per domain (the API writes no AQL; see `docs/architecture.md`, Layering); user input only through bind variables |

## Middleware

| Middleware | Behaviour |
|------------|-----------|
| CORS | origins from `LAWGRAPH_ALLOWED_ORIGINS` (default `localhost:5173`, `5174`, `127.0.0.1` variants); credentials allowed |
| Rate limit | sliding window per client IP: `LAWGRAPH_RATE_LIMIT_CALLS` (200) per `LAWGRAPH_RATE_LIMIT_PERIOD` seconds (60); 429 with `Retry-After`. Requests whose `Origin` is in the CORS allow-list are exempt. `X-Forwarded-For` is honoured only from loopback or `LAWGRAPH_TRUSTED_PROXIES`. State is per process, so N workers allow N times the limit |
| Cache-Control, ETag | every GET and HEAD answer says how it may be kept: a success at `/api/articles/`, `/api/judgments/` and `/api/stats` `public, max-age=60`, any other success `private, max-age=60`, anything else (an error, a 429) `no-store`. A success carries a weak `ETag` of the API version and the data version (`W/"<API version>-<data version>"`; `ArangoStore.data_version`: the revisions of the graph's collections, read at most every 15 s), the same for every answer of one release and one version of the data. A request with `If-None-Match` naming the current tag is 304; a write to the graph (a migration) or a new release changes the tag, so a browser that asks again after either gets the new answer within a minute |
| Request log | `[id] client METHOD path -> status size latency`; sets `X-Request-ID` |
| Compression | a response of 1 KB or more is sent gzip-compressed to a client that accepts it (`Accept-Encoding: gzip`), JSON and the Atom feed alike, with `Vary: Accept-Encoding`; a 304 has no body |

## Access

Every route reads and is public; there are no users, keys or roles. CORS allows `GET`,
`HEAD` and `OPTIONS` from `LAWGRAPH_ALLOWED_ORIGINS`.

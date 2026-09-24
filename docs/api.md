# API

A FastAPI service over the graph (`lawgraph.api.app:app`); it only reads. Start it with
`lawgraph-api` (uvicorn, `LAWGRAPH_API_HOST`:`LAWGRAPH_API_PORT`, default `127.0.0.1:8000`; set the host to `0.0.0.0` to serve other machines) or
`uvicorn lawgraph.api.app:app --reload`. The interactive schema is at `/docs`, the machine
schema at `/openapi.json`: every route has a summary, a tag and a typed answer, and every
route is a `GET` (`tests/api/test_openapi_schema.py` holds the schema to that), so a client
can generate its types from it.

## Endpoints

Paths are relative to the host. `bwb_id` is a BWB id (`BWBR0001854`); an instrument
route takes `bwb_id` or a CELEX number (`32016L0680`) for an EU act, in any case. A dossier `number`
matches `^\d+(-[A-Za-z0-9()]+)?$` (`29684`, `29684-I`, `21501-31`, `36956-(R2220)`), otherwise 422. A budget chapter is a dossier
of its own: `37020-XV` is not `37020`. Every dossier number the API returns (`number` of a
dossier, `dossier_number`, `dossier_numbers`, in either chamber) is written this way, so it can be used in a path
or a `dossier` filter as it is. List parameters `limit` and `offset` have the bounds shown in
`/docs`.

### Service

| Method | Path | Response |
|--------|------|----------|
| GET | `/` | `{"name": "lawgraph-api", "version": ...}` |
| GET | `/api/health` | `{"status": "ok", "database": "connected"}`, 503 when the database is unreachable |
| GET | `/api/stats` | document count per collection and edge count per relation |
| GET | `/api/stats/coverage` | the judgments whose text is loaded: `total`, `first_date`, `last_date`, per tier (`tiers`: `tier`, `count`, `first_date`, `last_date`, Hoge Raad first, `bijzonder` last) and per court (`courts`: `source`, `tier`, `court_code`, `court`, `count`, `first_date`, `last_date`, most first), and `stubs`, the judgments known only because a loaded one cites them. Every count of judgments in the API counts this selection, not the case law |

### Articles

| Path | Returns |
|------|---------|
| `/api/articles/{bwb_id}/{article_number}` | the article with its `parts` (aanhef, leden and onderdelen as spans of `text`), its instrument, citing judgments, `citations` (the resolved references, one per target) and `references` (every reference in the text, with the `leden`, `onderdelen` and `aanhef` it names, also when the target is not in the graph) |
| `.../history` | every version of the article, oldest first (only the last is `current`; empty for a law whose toestanden `retrieve bwb-history` has not loaded): validity period, text, `effect`, normalized `change` (`introduces`, `amends`, `repeals`), amending publication (`amended_by`) and commencement publication, each with its dossiers and its `parts`. The article is identified by `stam_id`, so renumbering does not break history; 404 for an unknown article |
| `.../legislative-history` | the dossiers that introduced, amended or repealed the article, or propose to: one entry per change and dossier (`dossier_id`, null for a dossier a publication names that is not in the graph, `dossier_number`, `dossier_title`, `change` `introduces`/`amends`/`repeals`, `status` `canoniek` for an amending publication, `voorgesteld` for a bill, `document_id`, `kind`, `date`, `summary` of that publication or bill), proposed first, then newest first. What only cites the article (a judgment, another article) is no history; the explanatory documents are at `explained-by`; empty list, never 404 |
| `.../explained-by` | the documents that `EXPLAINS` the article: edges to the article, to any of its versions (same `stam_id`) or to its instrument. `items[]`: `document` (`id`, `key`, `kind`, `title`, `date`, `dossier_number`, `chamber`, `source`, `is_explanatory`), `target` (`article`, `article_version`, `instrument`), `target_id`, `article_version_key`, `confidence`, `scope`, `section_anchor`. `scope` is `dossier` when the memorandum explains all changes of its dossier (`semantic tk-mvt`), `article` when the edge names the section about the article in `section_anchor` (`semantic tk-mvt-articles`; the `id` of a section of the document, whose text `GET /api/documents/{key}/passages` gives). An `instrument` item exists only for a dossier whose law changed no articles: no evidence about this article, listed after the article-level ones. Newest first; one item per document, level and anchor (a version before the article, the newest version first); `limit` (1-500, default 100), `offset`, `total` counts all; empty list for an unknown article, never 404 |
| `.../in-flux` | whether an open bill targets the article: `{in_flux, open_dossier_count}`; never 404 |
| `.../cited-by` | the passages of judgments that cite the article, one row per mention (`judgment`, `paragraph_id`, `paragraph_number`, the `leden`, `onderdelen` and `aanhef` it names, `snippet`, `confidence`), newest judgment first; `court`, `tier`, `lid` (a lid number the passage names), `limit` (max 200), `offset`, exact `total`; 404 for an unknown article |
| `.../relationships` | outgoing and incoming references with `semantic_type`, its explanation and confidence, the span of the reference (`start`, `end`, `text`, in the referring article) and the `leden`, `onderdelen` and `aanhef` it names, and annex scopes |

### Instruments and annexes

| Path | Returns |
|------|---------|
| `GET /api/instruments` | paged list; `q`, `jurisdiction` (`nl`, `eu`), `kind`, `article_count_min`, `sort` (default `title`) |
| `GET /api/instruments/{identifier}` | one instrument: identifiers, names, jurisdiction, kind, dates, article count. `identifier` is a BWB id, a CELEX number or a node key (`echr_convention`, `verdrag_012345`); 404 when unknown |
| `.../eu-links` | `implements` (EU acts whose CELEX number the instrument's text names) and `implemented_by` (regulations that name this act), each with `instrument`, `relation`, `confidence`, `basis`, `source`, `meta`; `international`: treaties that articles refer to (with the treaty article) and ECHR judgments that refer to the instrument or its articles, with the edge `meta`; `*_total` fields are absolute, `limit` (max 2000) bounds each list |
| `/api/instruments/{bwb_id}/articles` | articles in natural order (`24` before `24c` before `25`), each with its `breadcrumb` (the divisions it stands in: `type`, `label`, `title`); `include_stubs`, `text_preview_chars`, `limit` (max 2000), `offset` |
| `.../articles/at/{at_date}` | article versions valid on `YYYY-MM-DD` (`valid_from <= date < valid_until`) |
| `.../versions` | every toestand, newest first, `current` flagged |
| `.../amended-by` | amending publications (Staatsblad, Tractatenblad, ...) with edge counts per kind, articles affected, first effective date and dossiers; `limit`, `offset` |
| `.../dossiers` | dossiers through `LEGISLATED_IN` from the regulation itself (`via: instrument`) and from its amending publications (`via: amending_publication`, `publication` = newest) |
| `.../citations` | all edges touching the regulation's articles in one call; `relations` whitelist, `include_part_of` (default false), `max_edges` (default 20,000) |
| `.../judgments` | citing judgments with the cited articles |
| `.../related-instruments` | per related instrument, inbound and outbound article-level `REFERS_TO` counts |
| `.../cross-law-dependencies` | article references to other laws, with semantic type |
| `.../shared-annexes` | annexes shared with other laws |
| `GET /api/annexes` | annexes; `bwb_id`, `shared_across_laws` |
| `/api/annexes/{key}` and `.../referenced-by` | one annex with entries; the articles that scope by it |

`IMPLEMENTS` says that the text of a national regulation names the CELEX number of an EU act
(`basis: celex_named_in_text`, confidence 0.75). It is not a transposition relation and it
is not per article, so `eu-links` has no article list for it. `international` holds what
the graph links: `REFERS_TO` edges from articles to BWB treaties (`BWBV...`) and from ECHR
judgments to instruments and to articles of the ECHR Convention. Verdragenbank treaties and
Convention articles have no link from Dutch text, so nothing is returned for them.

`articles`, `citations`, `judgments`, `dossiers`, `amended-by`, `related-instruments` and
`cross-law-dependencies` answer for an EU act too; `bwb_id` in their response then holds the
CELEX number as requested. `versions`, `articles/at` and `shared-annexes` are about BWB
toestanden and annexes: for a CELEX number they are empty. An identifier that names nothing
gives an empty list on these routes, and 404 on the detail and on `eu-links`.

### Judgments

| Path | Returns |
|------|---------|
| `GET /api/judgments` | paged list; `q`, `court` (ECLI code), `tier` (`hoge_raad`, `gerechtshof`, `rechtbank`, `bijzonder`), `source`, `from`, `to`, `cited_by_min`, `sort` (`date_desc`, `date_asc`, `citation_count`); each item has `series_id` and `series_size` |
| `/api/judgments/{ecli}` | the judgment with its `paragraphs` (each with a `paragraph_id` for deep links, its printed `number` and the article `citations` in it, one per occurrence with `start` and `end`), the articles its `REFERS_TO` edges point at with their parent instrument (`articles`), and the same articles as `cited_articles` with the paragraphs that cite them, the lid or onderdeel named and a snippet. Citations are read from the stored edges; nothing is detected per request. `judgment.series_id` and `series_size` name the series of parallel cases it is one of (the same court, day and text), `series` the other judgments of it |

The judgments of one case are neighbours in `/api/nodes/judgments/{key}`: `APPEAL_OF` (appeal →
the judgment appealed), `ADVISES_ON` (the conclusion of an advocate-general → its judgment;
`meta.basis` `formal_relation` or `case_number`) and `ANSWERS` (a preliminary ruling → the
decision that asked its questions; `formal_relation` or `referral_text`). A judgment has the
inbound bucket, its conclusion or its referring decision the outbound one.

### Parliament

Every dossier in a list or a detail has `number` (its label), `suffix` (`XV` of `37020-XV`, null
without one), `same_number_count` (the other dossiers of its number: 24 for each dossier of a
budget of 25), `title`, `track` (what kind of dossier it is: `wetsvoorstel`,
`initiatiefwetsvoorstel`, `begroting`, `verdrag`, `initiatiefnota`, `nota` or `overig`; see
[data-model](data-model.md#parliament)), `current_stage`, `stages`, `closed`, `outcome`,
`opened_on`, `closed_on`, `stages_missing` (the stages the bill passed on its way to
`current_stage`, one of `stages` before it or one its track always passes, that have no dated
document, activity or vote in the graph, in stage order: `stemming` for a law without a vote on
record) and `stages_complete` (none missing; true for a dossier that is no bill). A
`subject` filter takes a number (`37035`: every dossier of that
number), a dossier (`37035-XXII`, `37035 xxii`) or words of the title.

`tk_url` of a Tweede Kamer document or activity, wherever it appears (timeline, document lists and
detail, node responses), is its page on tweedekamer.nl, made from the number the site knows: the
document number (`kamerstukken/detail?id=2026D44984&did=2026D44984`) or the activity number
(`debat_en_vergadering/plenaire_vergaderingen/details/activiteit?id=…` for a plenary kind,
`debat_en_vergadering/commissievergaderingen/details?id=…` for any other). It is null when the node
has no such number, as an Eerste Kamer paper, whose page is its `url`.

| Path | Returns |
|------|---------|
| `GET /api/dossiers?number=` | every dossier with that number (digits only, else 422), in the order of the Kamer: no suffix, numeric suffixes by value (`21501-02` before `21501-31`), budget chapters by value with their letter (`I`, `IIA`, `IIB`, `III`, ... `XXIII`), then the rest (the funds `A`, `B`, ..., `(R1519)`); `{total, items}`, empty for an unknown number |
| `GET /api/dossiers/open` | dossiers not closed (`closed` and `outcome` as in [data-model](data-model.md#parliament)); `committee` (slug), `subject`, `stage`, `has_stage` (all listed stages), `limit`, `offset` |
| `/api/dossiers/recent` | dossiers with an activity, a vote, a document or their closing in `days` (default 30), the most recent first; `subject`, `limit` |
| `/api/dossiers/{number}` | header (with `closed`, `outcome` `aangenomen`/`ingetrokken`/`verworpen` or null, `opened_on`, `closed_on`), current stage, counts of documents, activities, decisions, commitments, and the dossier hub: `instruments` (`id`, `key`, `bwb_id`, `celex`, `display_name`, `jurisdiction`, `relation` `legislated_in`/`amends`/`introduces`/`repeals`, `status` `canoniek`/`voorgesteld`; one item per instrument, relation and status), `committees` (leading an activity about the dossier, `role` `lead`), `documents_by_kind` (counts per document `kind`), `senate` (`document_count`, `first_date` of the Eerste Kamer papers), and `relations`: the dossiers it `revises` (a supplementary budget or slotwet: the budget of its chapter and year; `rule` `begrotingswijziging`/`slotwet`), `accompanies` (a budget change: the Voorjaarsnota, Najaarsnota or Miljoenennota its title names, `nota`) or is `related_to` (the Kamer relates a case of the one to a case of the other; `cases` counts the pairs, `case_kinds` names them, `Brief regering → Motie`), each with `direction` (`outgoing`: this dossier revises, accompanies, relates; `incoming`: the other one does) and the other `dossier` as a summary; ordered by relation, outgoing first, then by number |
| `.../timeline` | documents, activities, decisions and commitments; `order` (`desc`, `asc`), `kind` (comma-separated), `include_planned` (default true; false leaves out activities still `Gepland`), `limit`. Each entry has `after_closure` (dated after the dossier's `closed_on`: a follow-up letter or meeting, kept), `planned` (an activity with status `Gepland`), `node_type` and a `body` typed by it: a document (`kind`, `title`, `sequence`, `session_year`, `tk_url`, `url`, `chamber`, `source`, `is_explanatory`; never its text), an activity (`kind`, `agenda_title` (its subject), `number`, `status` as the source writes it: `Gepland`, also for a date that has passed or lies after the dossier closed, `Uitgevoerd`, `Geannuleerd`, `Verplaatst`, `Vervallen`; the entry also has `committee` `{key, slug, name}`, null for plenary), a decision (`subject`, `passed`, `vote_kind`, `tally`, `voters`, `external_id`, `primary_case_kind` (`Wetgeving` on the vote on the bill itself, `Amendement`, `Motie`, …), and the decided `document` with `dictum_excerpt` and `signatories`, each with `role`, `source_role`, `function` and `capacity`) or a commitment (`text`, `minister_name`, `minister_role`, `status`, `expected_resolution`) |
| `.../documents` | documents linked directly or through a case, newest first, with `total`; like every document in the API each has `chamber` (`TK`, `EK`, null for Staatsblad and Staatscourant), `source` and `is_explanatory` |
| `.../mutations` | the subgraph of `voorgesteld` edges, in graph shape |
| `/api/dossiers/documents/bulk?numbers=a,b` | top `per_dossier_limit` (default 8) documents per dossier |
| `GET /api/decisions`, `/{key}`, `/{key}/document` | decisions (`passed`, `primary_case_kind`, `party`, `chamber` `TK`/`EK`, `dossier` number; the Eerste Kamer has papers but no votes) with every vote cast — per member on a roll-call, per faction otherwise; the decided motion, amendment or bill with text |
| `GET /api/committees`, `/with-members`, `/{slug}` | committees; detail lists current members (`current_only=true`, the default) and a page of the dossiers it leads, newest first (`status` `open`/`closed`, `limit`, `offset`; `dossier_total` counts the matches, `active_dossier_count` the open dossiers) |
| `/api/committees/{slug}/activities` | the activities the committee leads, newest first, each with `date`, `kind`, `agenda_title`, `status`, `dossier_numbers`; `limit`, `offset`, `total`. The plenary is no committee: a plenary activity is led by none |
| `GET /api/members/{key}` | the member, with `birth_date`, `wikidata_id` and `government_functions`: every post they held in a Dutch cabinet (`function`, `cabinet`, `from_date`, `to_date`, oldest first; from Wikidata, complete from the 1970s; empty when Wikidata ties no person to the member). A minister who never sat in parliament has the name Wikidata gives; a cabinet member the Tweede Kamer has no person for is a member of their own (`wikidata_q<number>`) |
| `GET /api/members`, `/{key}`, `/{key}/votes`, `/{key}/dossiers`, `/{key}/touched-instruments` | members (filter `party`, `active`, `q`; ministers only with `include_all`); a member's votes, a faction vote counted only for the period they belonged to it; the dossiers the member authored documents in (`AUTHORED`), each a dossier summary plus `roles` (the source's role names), `functions` and `capacities` (what the member signed as there: `kamerlid`, `bewindspersoon`, `overig`, see [data-model](data-model.md#parliament)) and `document_count`, paged with `total`; in `/api/nodes/members/{key}` every `AUTHORED` edge carries `meta.role`, `meta.function` and `meta.capacity` of that signature; laws the member proposed changes to |
| `GET /api/factions`, `/{key}`, `/{key}/dossiers`, `/{key}/touched-instruments` | factions with member counts; the same two aggregates per faction (its dossiers are those its members signed documents in while they belonged to it) |
| `GET /api/parliament/seats` | seated factions with seat counts in plenary-hall order |
| `GET /api/parties/colors` | party abbreviation to hex colour |
| `GET /api/documents`, `/{key}` | documents across sources, metadata only, with `dossier_numbers` (`q`, `kind`, `chamber`, `source`, `dossier` number: documents linked directly or through a case; `limit` up to 1000, `offset`; `total` counts all matches); one with `tk_url` (its page), `file_url` (the original Word or PDF file of a Tweede Kamer document, from the Gegevensmagazijn), its extracted text (null when `normalize tk-content` has not reached it), its `sections` (the headings of the paper: `id`, `heading`, `level`, `parent`, `kind`, `number`, `number_scheme`, `article_refs`, `law`, `char_start`, `char_end`; offsets into `text`, empty without text), `dossier_numbers` (the dossiers it is `PART_OF`, in either chamber), `case_kinds` (the `Zaak.Soort` of its cases) and `explains` (the articles and instruments it `EXPLAINS`: `id`, `key`, `collection`, `bwb_id`, `article_number`; an article version resolves to its article, an instrument has no `article_number`) |
| `GET /api/documents/{key}/passages?bwb_id=&article=` | the sections of a memorandum that explain an article (or one of its versions), in document order: `section_id`, `heading`, `level`, `char_start`, `char_end`, `text`, `confidence` (uncalibrated), `match_type`; with `total`; empty list for an article without passages or a document without text, 404 for an unknown document |

### Graph, search, nodes

| Path | Returns |
|------|---------|
| `GET /api/graph/global` | instruments, articles, judgments and edges; `node_types` (`instrument`, `article`, `judgment`), `relations` (`REFERS_TO`, `EXPLAINS`, `PART_OF`, `IMPLEMENTS`, `AMENDS`), `max_judgments` |
| `/api/graph/instruments` | instruments as nodes, edges aggregated from article-level `REFERS_TO` plus the direct `IMPLEMENTS` and `AMENDS` edges; `relations` (`REFERS_TO`, `IMPLEMENTS`, `AMENDS`) |
| `/api/graph/judgments` | judgments and their edges; `max_judgments`, `include_stubs`. No relation or type filter: its edges are all aggregated `REFERS_TO`, its nodes judgments and the instruments they cite |
| `/api/nodes/{collection}/{key}` | a node (any node collection) with its neighbours in buckets of one relation, direction and neighbour collection. Every neighbour carries its edge: `edge_id` (the edge `_key`), `status`, `confidence`, `meta`. A bucket has `type`, `total` (its edges), `next_offset` (null on the last page) and `items`; `limit` (default 30, max 200) and `offset` page inside every bucket. Bucket and page order are the same on every request |
| `.../facets` | `items` of `{relation, direction, collection, type, count}` and `total` (all edges), counted in the database without reading the neighbours |
| `.../neighborhood` | nodes and edges within `depth` (1-4) hops, capped by `cap`; the filters below shape the traversal |
| `/api/nodes/in-flux`, `/api/nodes/heat` | node id to count of open proposed mutations; node id to incoming edges created in the last `months` (default 6), `min_count`. Both answer a plain map (`{"articles/bwbr0001854_287": 3}`), not validated through a response model |
| `GET /api/search?q=` | text search over `types` (`articles`, `committees`, `documents`, `dossiers`, `factions`, `instruments`, `judgments`, `members`; all by default), `kind`, `limit`. A citation in `q` (`art. 6:162 BW`, `artikel 287 Sr`, `Sr 287`, a full ECLI) puts its article or judgment first. Every hit has a `score`, its rank tier for `q`: an identifier of the hit (1), its whole name (0.75), the start of its name (0.5), every word of `q` in its name (0.25), a match on words only (0.1); a type lists its hits best first, ties in database order. `extra` of an article carries `instrument_title` (its law), of a document `dossier_number`, of a dossier `number`, `current_stage`, `closed` and `outcome` |
| `GET /api/resolve?q=` | the one node a citation, identifier or law name names: `kind` (`article`, `instrument`, `judgment`, `dossier`, `document`, or `none`), `match` (`id`, `key`, `collection`, `kind`, `display_name`, `confidence`), `confidence`, `alternatives` (up to five, same shape, best first) and `qualifier` (`derde lid` of `artikel 287, derde lid, Sr`). Nothing that fits is 200 with `kind` `none` and `match` null, so the caller searches the words instead; only an empty or over-long `q` is 422 |

### Resolve notations

`/api/resolve` reads `q` as, in this order:

| Notation | Examples | Target | Confidence |
|----------|----------|--------|------------|
| ECLI, BWB id, CELEX id | `ECLI:NL:HR:2023:123`, `BWBR0001854`, `32016R0679` | the judgment or instrument with that key | 1 |
| Article of a named law: keyword and number, or law and number | `art. 6:162 BW`, `artikel 287 Sr`, `artikel 3.26 van de Wet ruimtelijke ordening`, `Sr 287`, `Awb 3:4` | the article, by key; several articles (`artikelen 36e en 36f Sr`) give the first as match, the rest as alternatives | 0.95 |
| Kamerstuk | `36327`, `Kamerstuk 36327`, `36 327`, `29684-I` | the dossier with that number and suffix; other suffixes of the number are alternatives (0.5) | 0.95 |
| Paper of a Kamerstuk | `36327-3`, `Kamerstukken II 2020/21, 36327, nr. 3`, `kst-36327-3` | the document with that ondernummer in the dossier; the dossier (0.6) when the graph lacks the paper | 0.95 |
| Law name or abbreviation | `Wetboek van Strafvordering`, `Grondwet`, `Sr` | the instrument | 0.9; the start of a name 0.6, part of a name 0.4 |
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
| GET | `/api/relationships/search` | classified article relations; `type`, `law` (`bwb_id` of the source article) |

### Neighbour filters

`/api/nodes/{collection}/{key}`, `.../facets` and `.../neighborhood` take the same filters:
`relations` and `node_types` (comma-separated relation names and `NodeType` values),
`direction` (`outbound`, `inbound`) and `status` (`canoniek`, `voorgesteld`). A name that does
not exist is 422. On the node and facets routes they narrow the edges, so totals count what
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
- Errors: 401 missing or wrong key, 404 unknown resource, 422 invalid parameter, 429 rate
  limited, 503 database unreachable or writing not configured.
- Responses of the route handlers carry an `X-Request-ID` header.

## Layout

| Path | Contents |
|------|----------|
| `api/app.py` | app, middleware, router registration, `lawgraph-api` entry point |
| `api/routes/` | one module per domain (`articles`, `instruments`, `judgments`, `dossiers` (also `parties`), `committees` (also `members` and `factions`), `decisions`, `documents`, `graph`, `nodes`, `resolve`, `search`, `stats`, `relationships`, `annexes`, `parliament`) |
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
| Cache-Control | on 2xx GET: `/api/articles/` 30 min public, `/api/judgments/` 1 h public, `/api/stats` 5 min public, everything else `private, max-age=60` |
| Request log | `[id] client METHOD path -> status size latency`; sets `X-Request-ID` |

## Access

Every route reads and is public; there are no users, keys or roles. CORS allows `GET`,
`HEAD` and `OPTIONS` from `LAWGRAPH_ALLOWED_ORIGINS`.

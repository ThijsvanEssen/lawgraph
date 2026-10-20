# API

A FastAPI service over the graph (`lawgraph.api.app:app`); it only reads. Start it with
`lawgraph-api` (uvicorn, `LAWGRAPH_API_HOST`:`LAWGRAPH_API_PORT`, default `127.0.0.1:8000`; set the host to `0.0.0.0` to serve other machines) or
`uvicorn lawgraph.api.app:app --reload`. The interactive schema is at `/docs`, the machine
schema at `/openapi.json`: every route has a summary, a tag and a typed answer, and every
route is a `GET` (`tests/api/test_openapi_schema.py` holds the schema to that), so a client
can generate its types from it. `lawgraph openapi` prints that schema without a server;
`docs/openapi.json` is its output with the defaults of the settings, and
`tests/api/test_openapi_dump.py` keeps it current (all but `info.version`). Its `info` says how a client
paces itself: `x-request-timeout-ms` (`LAWGRAPH_API_REQUEST_TIMEOUT_MS`) and `x-rate-limit`
(`calls` per `period_seconds`); every `limit` has its `maximum` (`api/params.py`). The
warm-up asks the pages the front end asks first, as `data/first-pages.json` (a copy of the
explorer's) names them.

The schema documents each route: its parameters, its answer and what each field holds. This
page holds what is true across routes: addresses, periods, shared fields, errors, caching
and the middleware.

**Load lazily.** A page paints first on its cheapest call (about 0.4 s) and fills in the rest
afterwards. So a route that heads a page (the detail of a member, an article, a dossier) stays
cheap and never computes counts or lists; what is heavy is a route of its own, which the front
end asks for when it shows it; and a slow part of an answer has a budget: past it the answer
comes without that part, which it names in `partial` (the full search per type, the counts of
the feed), rather than keeping the whole answer waiting.

## Paths, parameters and periods

Paths are relative to the host. `bwb_id` is a BWB id (`BWBR0001854`) and `article_number` the
address of an article (its `address`): the number as the graph stores it (`287`, `8:54` of the
Awb, `bijlage 2 artikel 9` for an article of an annex, URL-encoded; `enig-artikel` for the one
article of a regulation of one article), or, for an article without a
number, the rest of its key (`stam_16464063`, the Algemene bepaling of the Grondwet; a repealed
identity `2_10_stam_2866303`), which stays across versions; an instrument
route takes `bwb_id` or a CELEX number (`32016L0680`) for an EU act, in any case. A law of the
Staatsblad the BWB does not hold (yet) is named by the publication that enacted it
(`STB-2026-56`) in the article routes (`/api/articles/STB-2026-56/2.8.6`) and on all instrument
routes, and by its key (`wet_stb_2026_56`); the publication itself is named by its own key
(`stb_2026_56`). A dossier `number`
matches `^\d+(-[A-Za-z0-9()]+)?$` (`29684`, `29684-I`, `21501-31`, `36956-(R2220)`), otherwise 422. A budget chapter is a dossier
of its own: `37020-XV` is not `37020`. Every dossier number the API returns (`number` of a
dossier, `dossier_number`, `dossier_numbers`, in either chamber) is written this way, so it can be used in a path
or a `dossier` filter as it is. Next to bare numbers stand their names as `/api/dossiers` gives them: `dossiers` (`{number, short_title, title}` per number, once each, in their order; null names for a number no dossier has) on a decision (list and detail), a paper of `/api/documents` (of `dossier_numbers`, else of `dossier_number`), a vote of an Eerste Kamer faction and an activity of a committee; `dossier_short_title` in the props of a paper, an activity or a decision among the neighbours of a node (of its first dossier); `short_title` on the dossier of a commitment and of a publication, in the props of a dossier node (`/api/nodes`, as the node, a neighbour and in a neighbourhood, also with `props=canvas`) and on each dossier of a law (`/api/instruments/{identifier}/dossiers`); `dossier_short_title` on each entry of an article's legislative history. List parameters `limit` and `offset` have the bounds shown in
`/docs`. Every paged list has a total order (its sort ends in a unique key, or reads an index
that orders ties by key), so walking its pages gives each row once.

A period on a list is two days, YYYY-MM-DD, both inclusive; one alone leaves the other side open: `from`/`to` on `/api/instruments` (the day it came into force, `date_in_force`; `published_from`/`published_to` the day it was published), `/api/commitments` (the day it was made) and `/api/decisions` and `/api/documents` (their date); `active_from`/`active_to` on `/api/members` (a seat or a post in a cabinet that overlaps it; of the Eerste Kamer the period the snapshots showed them), `/api/factions` (`active_from` to `active_until`) and `/api/committees` (`started_on` to `ended_on`; with a period also those that ended since). A period without a first day began at the start, one without a last day goes on.

The periods of articles and versions are half-open: `valid_until` is the first day a version is no longer in force (the start of the next), so `2021-07-01` means up to and including 2021-06-30, the "t/m 30-06-2021" of wetten.overheid.nl. An open period has `valid_until` null.

The periods of members and factions follow the Tweede Kamer and are inclusive: `to_date` (of a faction membership, a committee seat, a faction's `active_until`) is the last day, the Kamer's `TotEnMet`. Two successive periods touch: one ends the day before the next begins. An open period has `to_date` null.

Articles, their versions, instruments, their versions and publications carry `official_url`,
the official text (`core/official_urls.py`): an article on wetten.overheid.nl by its JCI
(`jci1.3:c:{BWB}&artikel={nr}`, with `&g={valid_from}` for a version; the regulation for an
article without a number the JCI can address), a BWB regulation as `/{BWB}` (a version
`/{BWB}/{valid_from}`), an EU act on EUR-Lex by its CELEX number, a treaty on the
Verdragenbank, a Staatsblad, Staatscourant or Tractatenblad publication on
zoek.officielebekendmakingen.nl (`stb-2019-33`; null before 1995, where that site begins).

## Shared fields

### Instruments

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
act and a law of the Staatsblad too; `bwb_id` in their response then holds the CELEX number as requested. `versions`, `delegated` and
`articles/at` are about BWB toestanden: for a CELEX number they are empty. An identifier that names nothing
gives an empty list on these routes, and 404 on the detail and on `eu-links`.

### Judgments

Every judgment the API names (the detail, its `conclusions`, `same_as`, `series` and
`cited_judgments`, the lists, the citing judgments of a law or article, the feed, a node) has
`cite`: `short` as a lawyer cites it (`HR 20 december 2019`, `Rb. Den Haag 6 juli 2026`,
`Conclusie A-G Hartlief 8 mei 2020`, `P-G` where its `advocate_general_role` is a
procureur-generaal; the place of a rechtbank or hof from its name, else from its court code)
and `full`, with its ECLI (`core.judgment_cite`).

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
`case_number`), empty for most; and `judgment.unresolved_citations`: the articles it cites of
laws that are not in the graph ("genoemd, niet in het netwerk": `law` as written, such as `Rv`,
`article_number`, `raw_match`, `qualifier`, `leden`, `onderdelen`, `aanhef`, `paragraph_ids`,
`mention_count`), one per law and article in reading order.

### Parliament

Every dossier in a list or a detail has `number` (its label), `suffix` (`XV` of `37020-XV`, null
without one), `same_number_count` (the other dossiers of its number: 24 for each dossier of a
budget of 25), `title`, `kind` (what the dossier is, as the Kamer names it: the `Zaak.Soort`
of its own zaak, `Wetgeving`, `Initiatiefwetgeving`, `Begroting`, `Verdrag`, `Initiatiefnota` or
`PKB/Structuurvisie`; null without one, "zonder soort": no kind is made up from its papers),
`kind_basis` (`case`: its zaak gives the kind; null without one), `phases` (of a `Wetgeving`, `Initiatiefwetgeving` or
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
vote, or the list of rejected bills), `retrieved_on`, and `attribution` (`LAWGRAPH_EK_ATTRIBUTION`: the
source to name with it); null when the Eerste Kamer has not decided; its outcome closes the
dossier: `aangenomen` or `verworpen` on the day of the vote, a Staatsblad publication dating an
adopted law),
`opened_on` (the day it opened, as the Kamer dates its papers: of nr. 1 of its own numbering,
the paper whose own dossier (`Document.Kamerstukdossier`) it is; else of its Koninklijke
boodschap; else of its first paper or activity) with `opened_on_basis` (`first_paper`,
`royal_message`, `earliest_record`), `submitted_on_tk` (the day the bill was submitted to the Tweede Kamer, as it dates it: `Zaak.GestartOp` of the dossier's own zaak of a bill), `last_activity` (the day of its newest paper, activity that
took place or decision; `sort=last_activity` lists by it, newest first), and `closed_on`. A
`subject` filter takes a number (`37035`: every dossier of that
number), a dossier (`37035-XXII`, `37035 xxii`) or words of the title.

`tk_url` of a Tweede Kamer document or activity, wherever it appears (timeline, document lists and
detail, node responses), is its page on tweedekamer.nl, made from the number the site knows: the
document number (`kamerstukken/detail?id=2026D44984&did=2026D44984`) or the activity number
(`debat_en_vergadering/plenaire_vergaderingen/details/activiteit?id=…` for a plenary kind,
`debat_en_vergadering/commissievergaderingen/details?id=…` for any other). It is null when the node
has no such number, as an Eerste Kamer paper, whose page is its `url`.

`number` of a document, wherever it appears (timeline, document lists and detail, search hits,
the feed, node responses: in `props`), is its number in its dossier as its chamber cites it: the
nr. of a Tweede Kamer paper (`12`, its `sequence` as text), the letter of an Eerste Kamer one
(`A`, which has no `sequence`). Read it rather than `sequence`; it is null for a paper numbered
in no dossier.

`sender` of a Tweede Kamer document, in the same places but search hits (the feed has `persons`
and `ministry`), is who sent it as the source signs it: its first signatory, else the signature
the source calls its `Afzender` (the griffier). `name`, `function` (`minister van Financiën`,
`Tweede Kamerlid`), `faction`, `capacity` (`bewindspersoon`: a letter of the government,
`kamerlid`, `overig`), `member_key` and, of a bewindspersoon, the `ministry` the function names on
the document's date. Null for an Eerste Kamer paper and a paper without signatures.

The Eerste Kamer (`?chamber=EK` on the lists of factions, committees and members and on the
seats) is what eerstekamer.nl shows on the day it was read: the site gives the composition of
today, and no start or end of a membership as data. So a period is what was observed:
`observed_from` is the day of the first snapshot that showed it, `observed_until` the day of
the first that no longer did (null while it is shown); neither is the day it began or ended,
and nothing before the first snapshot is known. A member's `ek` holds `name` (as the Kamer
writes it, `mr. B.O. Dittrich`), `faction` (key) and `abbreviation`, `seniority_days`
(`Anciënniteit`: the days served, earlier terms included; no start date), `residence`,
`seat` (where Wie zit waar seats them: `block` `left` or `right` seen from the government, or
`chair` for the Voorzitter, `row` from the government, `column` from the outer wall; null for
nowhere), `observed_from`, `observed_until` and `source`. The seats of the Eerste Kamer
(`/api/parliament/seats?chamber=EK`) carry `hall`: its `url` and every seat a member holds
(`block`, `row`, `column`, `faction`, `abbreviation`, `member`, `name`), the left block, the
chair and the right block row by row; a place no one holds is not listed. Wie zit waar shows
today's plan only, so `hall_read_on` is the day it was read: with a `date` before that day
`hall` is null (no source keeps an earlier plan). The Tweede Kamer has no `hall` (its open data
places no seat). Everything taken over from eerstekamer.nl
carries `source` (`url`, `retrieved_on`, `composition_date`: the day of the composition shown,
`data_since`: the day of the first snapshot, before which nothing is known, and `attribution`:
`LAWGRAPH_EK_ATTRIBUTION`, to name with it).
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
| `publicatie` | a publication in the Staatsblad, Staatscourant or Tractatenblad; `publication.instruments` holds the laws it enacts (`effect` `establishes`: the regulations whose `enacted_publication` it is, with their `article_count`), then those it changes (`amends`, `introduces` or `repeals` where every `AMENDS`, `INTRODUCES` or `REPEALS` it makes in the law is of that kind, else `amends`; `article_count` the articles it touches), by title, at most ten | instrument of kind `publicatie`, `date_published` |
| `inwerkingtreding` | a new version (toestand) of a law in force; `commencement` holds `changed_articles` and `articles` (the numbers of the articles with a version that begins that day, in the order of the law, at most fifty), `new` (the day is the law's own `date_in_force`: it comes into force), `publication` (`key`, `series`, `year`, `number`, `citation` (`Stb. 2026, 204`), `path`: the publication most of those versions name as their `origin_publication`, of a new law the one that enacted it; `key` null when the graph lacks it) and `based_on` (`instrument`, `kind` of the regulation itself in lower case, `articles`: the law its preamble names most articles of, `BASED_ON`, as `/delegated` has it; null for none) | instrument version, `valid_from`: the start of the toestand as the BWB lists it (`retrieve bwb-history`). A date ahead appears once the BWB holds that toestand; a commencement a besluit names but the BWB does not yet list is not in the feed |
| `uitspraak` | a judgment or conclusion published on uitspraken.rechtspraak.nl, **only when asked for** (`kind=uitspraak` or `tier`): a feed without `kind` holds parliament and legislation, every kind but this one, while its `kind` facet still counts the judgments; without `tier` of the highest courts (`hoge_raad`, `raad_van_state`, `centrale_raad_van_beroep`, `college_van_beroep_bedrijfsleven`) and the Parket (`parket`), not a stub nor a publication another replaces; the item's `judgment` holds its `ecli`, `court`, `tier`, `court_kind`, `decision_kind`, `procedure`, `decided_on` and, of a conclusion, `advocate_general` and `advocate_general_role`, and how it ended (`outcome`, `outcome_text`, `conclusion_outcome`, `conclusion_outcome_text`, `echr_findings`, as on the detail); `summary` is its inhoudsindicatie | judgment, `published_on` ("Datum publicatie"): a judgment is news when it appears, often weeks after `decided_on`; one without a published document (no `published_on`) is not in the feed |

Each item: `id` (`collection/key` of its node), `kind`, `date` (no time of day; the source
gives none), `title` (a bill the title of its dossier, a commitment its first words, another
paper or a vote its subject, a publication its citation title, a version the title of its
law), `summary` (the text of a commitment, the
decision of a vote, `Aangenomen.`; else null), `has_text` (of a paper: whether its text is in
the data, so a row can open on it; a new paper's text follows its PDF by days; null for the
other kinds), `dictum` (of a motion what it asks or says, as `/api/documents/{key}` gives it;
else null; both from `lg_document_light`, not from the paper's props), `subkind` (the whole `Document.Soort`,
`Motie (gewijzigd/nader)`; for a vote what was voted on, the `Zaak.Soort`: `Motie`,
`Amendement`, `Wetgeving`, …, null when the Kamer names no one Soort), `dossier` short titles: `short_title` the name the dossier goes by and `short_title_basis` where it comes from: `title` (of a budget its chapter and year, else the parentheses that end the title, as in `/api/dossiers`), else official data of its bill: `citation` (the citation title the bill gives itself, "Deze wet wordt aangehaald als: …"), `case` (the citation title the Kamer gives the bill's case), `amended_law` (the citation title of the one Dutch law the bill changes: then it names that law, not the bill); both null when there is none, `headline` (the parts a headline is made of:
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
as the source writes it, and how it was decided as the Kamer writes it: `method` of the Eerste Kamer, `Hamerstuk`,
`Stemming bij zitten en opstaan, aangenomen`, and `decision_kind` of the Tweede Kamer, its `BesluitSoort`,
`Stemmen - zonder stemming aannemen` for a hamerstuk; of the Tweede Kamer `coalition` as `/api/decisions/{key}`
gives it, and `coalition_factions`, each coalition faction that cast a seat, most seats first: `key`, `short`,
`choice` `Voor`/`Tegen` (null when its seats went both ways, a roll call), `seats_for`, `seats_against`;
null and `[]` without a cabinet or a coalition vote and in the Eerste Kamer), `commitment` (`status`, `expected_resolution`), `publication`
(`series` `stb`/`stcrt`/`trb`, `year`, `number`, `citation` (`Stb. 2026, 94`), `instruments`: the laws it amends,
introduces or repeals, up to ten, `key`, `title`, `official_url`), `commencement`
(`instrument`, `article_count` of the law, `changed_articles`: the articles with a version
that begins that day).

### Completeness

What the graph holds of a record or a source, and what it lacks, has one shape
(`core/completeness.py`, `api/schemas/completeness.py`):

```
completeness: {<part>: {state, as_of, missing}}
```

| Part | About |
|------|-------|
| `text` | its text |
| `paragraphs` | its paragraphs with lasting ids |
| `tables` | the tables in its text |
| `references` | the references in its text, linked |
| `definitions` | the definitions it gives |
| `versions` | its versions over time |
| `succession` | its successor and predecessor (old to new law) |
| `source` | the source itself: whether the runs still fetch from it |

| State | Meaning |
|-------|---------|
| `done` | the step ran and holds all it found |
| `partial` | it ran and left some; `missing` how many |
| `none` | it ran and found nothing |
| `pending` | the step has not reached it yet |
| `paused` | the source or the step is off |
| `unavailable` | the source refused the last run (HTTP 401/403, a challenge page) |
| `not_in_source` | the source does not give it |

A part left out is not known to lack anything. Every state is derived from what a step wrote
or a run recorded, never set by hand.

Of a source (`data_as_of.<source>.completeness.source`, in `/api/stats` and the feed): after
its steps, `<phase> all` and a poll keep per source whose retrieves they had what they did
(`pipeline_state` `source <name>`, `pipelines/source_runs.py`): `paused` when it is off
(`LAWGRAPH_SOURCES_OFF`), `unavailable` when one of its retrieves ended so, `done` when all
ended well; a failed or skipped retrieve records nothing. `as_of` is when its retrieves last
all ended well, else when its newest record was fetched. A source no run recorded yet is
`done` as of that record, or `pending` when nothing of it was fetched.

### Resolve notations

`/api/resolve` reads `q` as, in this order:

| Notation | Examples | Target | Confidence |
|----------|----------|--------|------------|
| ECLI, BWB id, CELEX id | `ECLI:NL:HR:2023:123`, `BWBR0001854`, `32016R0679` | the judgment or instrument with that key | 1 |
| Number of a toezegging | `TZ202603-130` | the commitment with that `number` | 1 |
| Article of a named law: keyword and number, or law and number | `art. 6:162 BW`, `artikel 287 Sr`, `artikel 3.26 van de Wet ruimtelijke ordening`, `Sr 287`, `Awb 3:4` | the article, by key; several articles (`artikelen 36e en 36f Sr`) give the first as match, the rest as alternatives | 0.95 |
| Publication | `Stb. 2026, 94`, `Staatscourant 2026, 12345`, `Trb. 2018, 201` | the instrument with that key (`stb_2026_94`) | 1 |
| Kamerstuk | `36327`, `Kamerstuk 36327`, `36 327`, `29684-I`, `23908-(R1519)` | the dossier with that number and suffix; other suffixes of the number are alternatives (0.5) | 0.95 |
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

### Neighbour filters

`/api/nodes/{collection}/{key}` and `.../neighborhood` take the same filters:
`relations` and `node_types` (comma-separated relation names and `NodeType` values),
`direction` (`outbound`, `inbound`) and `status` (`canoniek`, `voorgesteld`). A name that does
not exist is 422. On the node route they narrow the edges, so totals count what
remains. On `.../neighborhood` they shape the walk: it follows only edges of those relations
and status, only in that direction (at every hop), and only through nodes of those types (the
focal node is always kept); the edges returned between the kept nodes are those of the
relations and status.

## Rendered pages

`GET /render/{path}` answers the HTML of a page of Concordans, for every path that is no file and no `/api` (Caddy rewrites it here); not in the OpenAPI schema. The shell of the front end (its built `index.html`, `LAWGRAPH_SPA_INDEX`, read again when the file changes) with, for a readable address of a source (`core/readable_paths.py`, the same as the front end's `leesbaar.ts`; `tests/data/readable-paths.json` holds the cases both are tested against), in `<head>` its `<title>`, description, canonical address (`LAWGRAPH_SITE_URL`, without the query), Open Graph and JSON-LD (`Legislation` for a law, an article and an annex, `CreativeWork` for a judgment, a paper, a zaak and a dossier, `Person` for a member, `Organization` for a faction and a committee, `GovernmentOrganization` for a cabinet, `Legislation` for a publication, `CreativeWork` for a commitment and a decision, `Event` for an activity, and a `BreadcrumbList`), each tag marked `data-seo`, the node of the page in `<meta name="focus" content="<collection>/<key>" data-seo />` (the app opens it without a lookup), and before the div of the app a `<main id="seo">` with its breadcrumbs (as its JSON-LD has them), its content and plain links, only to pages that are indexed (a paper of a list whose page is not is named without a link): a law its articles; an EU act (`/wetten/32022L2555`, by its CELEX number) its whole title, its articles and its text on EUR-Lex (not indexed without articles: its text was not read); an article its text, the articles and laws it refers to, the articles that refer to it, the papers that explain it, the judgments that cite it (the most cited first, 20) and the 5 articles before and after it in its law; an annex (`/wetten/BWBR0002741/bijlage/II`) its law, description and entries (not indexed without either); a judgment its summary, its text (its paragraphs: a heading as a heading, a consideration with its number and its id, no table of contents), the articles and judgments it cites, the judgments that cite it (the most cited first, 20) and those of its case or related to it (`APPEAL_OF`, `CONTINUES`, `REFERRED_BY`, `ADVISES_ON`, `ANSWERS`, `RELATED_TO`, either way); a paper its kind, submitters, dossier, the dictum of a motion when `lg_document_light` has one, its text (a heading of its `sections` as a heading), the vote on it per faction, its zaak, signers, attachments, the paper it is an attachment of, the activity it was made in, what it answers and what answers it, what it explains, what it refers to and what cites it (20 of each) and the papers numbered before and after it in its dossier (not indexed without its text, but a motion or an amendment with its dictum); a dossier its newest 200 papers (not indexed without one); a zaak (`/zaken/2025Z15468`) its kind, start, its first dossier the graph has (also its breadcrumb), its papers (20, oldest first) and the decisions on it (not indexed for a motion or an amendment: the page of its paper is the one to find); an activity (`/activiteiten/2026A01323`, `Event`) its kind, day and subject, its committee, its dossiers, its stenogram and verslag, the motions submitted and the commitments made in it and the decisions taken in it (not indexed without a paper or commitment made in it); a member what they are now as the source says it (their post in a cabinet, else a seat in a chamber, `oud-Kamerlid` once every seat in the Tweede Kamer ended, else their name alone), their posts per cabinet, their factions and the newest 20 papers they signed (`noindex` for a member without a role, [data model](data-model.md)); a bare member who is the same person as a member with a role (`SAME_AS`, `semantic tk-person-duplicates`) is a 301 to theirs; a faction and a committee their members now (with their role); a cabinet its prime minister, the cabinet before it, its parties, phases and bewindspersonen with their posts; a publication its title (that of its nota van toelichting, never the name of the series alone; not indexed without one and without a regulation it changes), its dates, the regulations it or its nota introduces, amends, repeals or explains, its dossiers and its page on officielebekendmakingen.nl; a commitment its text, the debate it was made in (kind and day) and the day the Kamer registered it, who made it in which post, the cabinet, its status, its dossiers and the letters that fulfil it; a decision the papers it was taken on, its dossiers and who voted for and against (a vote on one motion or amendment indexed with the page of that paper as its canonical address, which holds the vote too; any other not indexed). The text of a judgment or a paper up to 100,000 characters, cut after a whole paragraph (the whole text of 95 in 100). Light reads only, within 1 s; past it the page's title and description from the props of its node alone (as `title` of `/api/nodes`), its node as focus and its canonical address, without its content (`no-store`), the shell alone when even its node is not read within 0.5 s more. Another spelling of a readable address (`ecli:nl:…`, `bwbr…`) and `/explore?focus=<collection>/<key>` of a node that has one are a 301 to it, the rest of the query kept; a law or an article of it by the abbreviation it is cited by (`/wetten/wft/artikel/1:1`, `/wetten/bw/artikel/6:162`, `/api/lookup`) is a 301 to its BWB id or CELEX number, an abbreviation of no law 404; a page of the app (`spa-routes.json` beside the shell; a `[param]` in its path stands for any one segment, `/bundels/[id]`) is the shell with its own title, the start page (`/`) with its content too, read of nothing (`api/seo/pages/home.py`: the heading, what Concordans is, a search form that works without scripts, `GET /?q=`, and the three ways in, each with its example, as the app draws them; JSON-LD `WebSite` with a `SearchAction` on `/?q={search_term_string}` and its publisher), and `noindex` when its route says `"index": false` (a reader's own bundels, kept in the browser); `/gemarkeerd` is a 301 to `/bundels` (the query kept) and `/gemarkeerd/bundel?id=<id>` to `/bundels/<id>`, once the front end lists the new page and no longer the old one; an address of a source the graph lacks and any other path are 404, the shell titled `Niet gevonden, Concordans` with `noindex` (without `spa-routes.json` every such path is the shell, 200). A page and a 404 are `no-cache` (they name the chunks of the current front end), a page with a weak `ETag` of the API, the shell and the data version (304 on `If-None-Match`), a 301 a day; 503 with `Retry-After` when the database is gone

## Response conventions

- Every DTO forbids unknown fields (`extra="forbid"`).
- Node references use `id` (`collection/key`) and `key`; edges use `from` and `to`.
- A reference to another source by its identifier carries the node id too (`translation_of_id`, a conclusion's `id`, a dossier reference's `id`), so a client builds no key.
- Every `collection` and every upper-case `relation` is an enum of the catalogue (`Collection`, `Relation`); `tests/data/relations.json` gives the relations with the collections they join.
- An article's `display_name` is the article as it is cited (`Art. 6:162 BW`, `Art. 287 Sr`; `core.names.article_cite`) on a node, a reference to one, an article's detail, a search hit and a match of `/api/resolve`; its long name (`Artikel 162 Burgerlijk Wetboek Boek 6`) stays in its `props`.
- A paper or a case has `kind_group` beside its `kind` (`motie`, `amendement`, `wetsvoorstel`, `brief`, `overig`); a node of one in its `props` too, an item of the feed of a paper or a vote by its `subkind`, a link of the feed to a paper by its `kind`.
- A source (a node, a reference to one, a row of a list, a search hit, an item of the feed) has its readable address in `path` (`/wetten/BWBR0005289/artikel/6:162`, `/wetten/32022L2555` (an EU act by its CELEX number; its articles `/wetten/32022L2555/artikel/21`), `/uitspraken/ECLI:NL:HR:2019:2006`, `/dossiers/36600-VIII`, `/kamerstukken/36600-VIII/5`, `/stemmingen/<key>`, `/stb/2026/94`, `/wetten/BWBR0002741/bijlage/II`, `/zaken/2025Z15468`, `/activiteiten/2026A01323`, `/leden/<slug>`, `/kabinetten/<key>`, `/fracties/<key>`, `/commissies/<slug>`, `/toezeggingen/TZ…`): the address of its page on Concordans, where the server gives its HTML (`/render`). It is computed from the fields of the answer by one function (`core/readable_paths.py`; `tests/data/readable-paths.json` holds the cases the front end is tested against too); null for a source without one (an activity of the Eerste Kamer, the one annex of a regulation without a label, a paper the Kamer has not numbered yet, a version of a law) and where the answer lacks what makes it, rather than a wrong one (a paper whose dossier suffix it does not give, a member without a slug).
- List responses carry `items` and `total`, the absolute number of matches independent of
  `limit`. Some carry a domain name instead of `items` (`entries` for timelines, `versions`,
  `votes`, `relationships`). The neighbours of a node are grouped in `buckets`, each with its
  own `items`, `total` and `next_offset`.
- Errors are JSON `{"detail": "<a sentence>"}`, in English, and never name their cause (a
  statement, a path, a setting: that goes to the log). `api/errors.py` makes every one:
  - 404 what is not there, `"<What> '<key>' not found."` (`NotFound` in
    `db/queries/not_found.py`; a path no route serves is `Route '<path>'`);
  - 422 every parameter the API cannot answer, whether FastAPI's own validation or a check of
    the route (`Invalid`): `` "`param`: what is wrong." ``, the parameter first, and
    `Allowed: …` where the choice is closed (a collection the API does not serve, a search
    type). The API answers no 400;
  - 429 rate limited;
  - 503 with `Retry-After: 30` from any route when the database is unreachable or refused
    (an outdated schema, another collation; until the API restarts) or when its reads ran
    past `LAWGRAPH_API_REQUEST_TIMEOUT_MS` (30 s for the request in all) or
    `LAWGRAPH_READ_TIMEOUT_MS`; and from `/api/nodes/heat` while the heat is not counted
    yet (`Retry-After: 3600`);
  - 500 any other error: `{"detail": "Internal error.", "request_id": "…"}`, the id of its
    `X-Request-ID` header and of its line in the request log, which holds the traceback.
- Every response that passes the request log carries an `X-Request-ID` header.

## Layout

| Path | Contents |
|------|----------|
| `api/app.py` | app, lifespan (warm-up and search terms at the start; terms written and stores closed at the end), router registration, `lawgraph-api` entry point |
| `api/errors.py` | the shape of every error, `Invalid` (422) and the handlers |
| `api/middleware.py` | the request log, cache headers and `ETag`, rate limit, read deadline and cancel on disconnect |
| `api/routes/` | one module per URL prefix: `routes/<name>.py` serves `/api/<name>` (`render` serves `/render`) |
| `api/schemas/` | Pydantic DTOs, one module per route module; shared ones in `common.py`, `actors.py` (members and factions) and `ek_source.py` (where something of the Eerste Kamer was read) |
| `api/actors.py` | what the member and faction routes answer alike: the dossiers they authored in, the laws they change most |
| `api/params.py` | parsing of query parameters shared by routes (comma-separated choices, 422 on a value that does not exist) |
| `api/dependencies.py` | `get_store()`: one shared store (`GraphStore`, on PostgreSQL) |
| `db/queries/` | the queries of the routes, one module per domain (the API writes no SQL; see `docs/architecture.md`, Layering); user input only through bind variables |

## Middleware

| Middleware | Behaviour |
|------------|-----------|
| CORS | origins from `LAWGRAPH_ALLOWED_ORIGINS` (default `localhost:5173`, `5174`, `127.0.0.1` variants); credentials allowed |
| Rate limit | sliding window per client (an IPv4 address, an IPv6 /64), on a monotonic clock: `LAWGRAPH_RATE_LIMIT_CALLS` (200) per `LAWGRAPH_RATE_LIMIT_PERIOD` seconds (60); 429 with `Retry-After`. Every request counts, whatever its `Origin`. `X-Forwarded-For` is honoured only from loopback or `LAWGRAPH_TRUSTED_PROXIES`, and then its right-most address that is no such proxy is the client. State is per process, so N workers allow N times the limit; clients without a request in the window are forgotten once per window |
| Cache-Control, ETag | every GET and HEAD answer says how it may be kept: a success at `/api/articles/`, `/api/judgments/` and `/api/stats` `public, max-age=60`, any other success `private, max-age=60`, anything else (an error, a 429) `no-store`. A success carries a weak `ETag` of the API version and the data version (`W/"<API version>-<data version>"`; `version_cache.current_version`: the revisions of the graph's collections, read at most every 2 s per process, on a thread of its own, a request waiting 0.5 s at most for a new read before it takes the version it knows), the same for every answer of one release and one version of the data. A request with `If-None-Match` naming the current tag is 304; a write to the graph (a migration) or a new release changes the tag, so a browser that asks again after either gets the new answer within a minute |
| Request log | `[id] client METHOD path -> status size latency`; sets `X-Request-ID`; answers an error no handler answers with the 500 of `api/errors.py` |
| Compression | a response of 1 KB or more is sent gzip-compressed to a client that accepts it (`Accept-Encoding: gzip`), JSON and the Atom feed alike, with `Vary: Accept-Encoding`; a 304 has no body |

## Access

Every route reads and is public; there are no users, keys or roles. CORS allows `GET`,
`HEAD` and `OPTIONS` from `LAWGRAPH_ALLOWED_ORIGINS`.
